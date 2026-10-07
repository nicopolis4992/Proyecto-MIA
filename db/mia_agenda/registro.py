"""SCRUM-74 — Registro de la cita propuesta.

Punto de entrada para el agente de agenda (nodo de LangGraph u otro):

    from mia_agenda import registrar_cita_propuesta, PropuestaCita, ...
    resultado = registrar_cita_propuesta(conexion, propuesta, seud, cif)

La función:
  1. valida la propuesta en Python (errores legibles antes de tocar la base);
  2. seudonimiza y cifra los datos de contacto (la base nunca los ve en claro);
  3. llama a ``mia.fn_registrar_cita`` —la única puerta de escritura— que deja
     la cita en estado ``pendiente_aprobacion`` y es idempotente.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from .seguridad import Cifrador, Seudonimizador, normalizar_telefono

CENTAVO = Decimal("0.01")
TEMPERAMENTOS = {"tranquilo", "nervioso", "agresivo"}
TIPOS_DESCUENTO = {"primera_vez", "fidelidad", "referido",
                   "multi_mascota", "fidelidad_mensual"}   # los dos últimos: tarifario v2


class PropuestaInvalida(ValueError):
    """La propuesta no cumple las reglas mínimas; no se registra nada."""


def _dinero(valor: Any, campo: str) -> Decimal:
    """Montos siempre en Decimal con 2 decimales; nunca float (0.1 + 0.2 ≠ 0.3)."""
    if isinstance(valor, float):
        raise PropuestaInvalida(f"{campo}: use Decimal o texto, no float ({valor!r})")
    try:
        d = Decimal(str(valor))
    except Exception as exc:  # noqa: BLE001
        raise PropuestaInvalida(f"{campo}: monto inválido {valor!r}") from exc
    if d < 0:
        raise PropuestaInvalida(f"{campo}: no puede ser negativo ({d})")
    return d.quantize(CENTAVO, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Cotizacion:
    """Resultado del motor de tarifas de SCRUM-98 para UNA mascota y servicio."""
    precio_estimado: Decimal
    es_comprometido: bool
    semiamplitud: Decimal = Decimal("0.00")
    atributos_no_declarados: tuple[str, ...] = ()
    desglose: dict = field(default_factory=dict)

    @classmethod
    def desde_motor(cls, salida: dict) -> "Cotizacion":
        """Adaptador de la salida del motor de SCRUM-98.

        NOTA: los nombres de clave deben alinearse con el código real de
        ``tarifario_v1`` cuando se integren ambos repositorios.
        """
        return cls(
            precio_estimado=_dinero(salida["precio_estimado"], "precio_estimado"),
            es_comprometido=bool(salida["es_comprometido"]),
            semiamplitud=_dinero(salida.get("semiamplitud", "0"), "semiamplitud"),
            atributos_no_declarados=tuple(salida.get("atributos_no_declarados", ())),
            desglose=dict(salida.get("desglose", {})),
        )


@dataclass(frozen=True)
class Tercero:
    """Dueño de la mascota distinto de quien escribe (prima, vecina, amiga)."""
    nombre: str
    telefono: Optional[str] = None


@dataclass(frozen=True)
class Mascota:
    nombre: str
    raza: Optional[str] = None
    temperamento: Optional[str] = None
    duenio: Optional[Tercero] = None      # None = la mascota es del solicitante


@dataclass(frozen=True)
class Linea:
    mascota: Mascota
    servicio: str                          # tarifario v2 (express, basico, completo, premium, deslanado) o siglas del Excel
    cotizacion: Cotizacion


@dataclass(frozen=True)
class Descuento:
    tipo: str                              # primera_vez | fidelidad | referido | multi_mascota | fidelidad_mensual
    detalle: Optional[str] = None
    monto: Decimal = Decimal("0.00")       # 0 si el beneficio es en especie


@dataclass(frozen=True)
class PropuestaCita:
    clave_idempotencia: str                # wamid del mensaje que cerró la propuesta
    telefono_solicitante: str
    nombre_solicitante: str
    origen: str                            # LINAS | LAVET | HOSPEDAJE
    inicio: datetime
    fin: datetime
    lineas: tuple[Linea, ...]
    tarifario_version: str
    puerta_a_puerta: bool = False
    costo_traslado: Decimal = Decimal("0.00")
    direccion: Optional[str] = None
    dentro_perimetro_urbano: Optional[bool] = None
    descuento: Optional[Descuento] = None
    telefono_referente: Optional[str] = None   # quién recomendó al solicitante
    # Datos operativos del prototipo
    sector: Optional[str] = None               # barrio para el traslado (no la dirección)
    pedido_especial: Optional[str] = None
    requiere_revision_manual: bool = False


@dataclass(frozen=True)
class ResultadoRegistro:
    cita_id: int
    creada: bool          # False = la clave ya existía (reintento): no se duplicó


def validar(p: PropuestaCita) -> None:
    errores: list[str] = []
    if not p.clave_idempotencia or not p.clave_idempotencia.strip():
        errores.append("clave_idempotencia vacía")
    try:
        normalizar_telefono(p.telefono_solicitante)
    except ValueError as exc:
        errores.append(str(exc))
    if not p.nombre_solicitante.strip():
        errores.append("nombre del solicitante vacío")
    if p.inicio.tzinfo is None or p.fin.tzinfo is None:
        errores.append("inicio y fin deben incluir zona horaria (America/Guayaquil)")
    elif p.fin <= p.inicio:
        errores.append("fin debe ser posterior a inicio")
    elif p.fin - p.inicio > timedelta(hours=12):   # un desenredo severo ocupa el día
        errores.append("una cita no puede durar más de 12 horas")
    if not p.lineas:
        errores.append("la propuesta no tiene mascotas")
    vistos = set()
    for i, ln in enumerate(p.lineas, start=1):
        if not ln.mascota.nombre.strip():
            errores.append(f"línea {i}: mascota sin nombre")
        if ln.mascota.temperamento and ln.mascota.temperamento not in TEMPERAMENTOS:
            errores.append(f"línea {i}: temperamento '{ln.mascota.temperamento}' no reconocido")
        if ln.cotizacion.semiamplitud > ln.cotizacion.precio_estimado:
            errores.append(f"línea {i}: la banda de precio no puede bajar de 0")
        clave = (ln.mascota.nombre.strip().lower(), ln.mascota.duenio, ln.servicio)
        if clave in vistos:
            errores.append(f"línea {i}: mascota y servicio repetidos")
        vistos.add(clave)
        if ln.mascota.duenio and ln.mascota.duenio.telefono:
            try:
                normalizar_telefono(ln.mascota.duenio.telefono)
            except ValueError as exc:
                errores.append(f"línea {i}: {exc}")
    if p.puerta_a_puerta:
        if not p.direccion:
            errores.append("puerta a puerta requiere dirección")
        if p.dentro_perimetro_urbano is None:
            errores.append("puerta a puerta requiere indicar si está dentro del perímetro urbano (SCRUM-73)")
    elif p.costo_traslado:
        errores.append("costo de traslado sin servicio puerta a puerta")
    if p.descuento and p.descuento.tipo not in TIPOS_DESCUENTO:
        errores.append(f"tipo de descuento '{p.descuento.tipo}' no reconocido")
    if errores:
        raise PropuestaInvalida("; ".join(errores))


def _b64(dato: Optional[bytes]) -> Optional[str]:
    return None if dato is None else base64.b64encode(dato).decode("ascii")


def construir_payload(p: PropuestaCita, seud: Seudonimizador, cif: Cifrador) -> dict:
    """Arma el JSON para la base. No contiene ningún dato de contacto en claro."""
    validar(p)
    solicitante: dict[str, Any] = {
        "identificador_hmac": seud.de_telefono(p.telefono_solicitante),
        "telefono_cifrado": _b64(cif.cifrar(normalizar_telefono(p.telefono_solicitante))),
        "nombre_cifrado": _b64(cif.cifrar(p.nombre_solicitante.strip())),
    }
    if p.telefono_referente:
        solicitante["referido_por_hmac"] = seud.de_telefono(p.telefono_referente)

    lineas = []
    for ln in p.lineas:
        m = ln.mascota
        if m.duenio is None:
            propietario: Any = "solicitante"
        elif m.duenio.telefono:
            propietario = {
                "identificador_hmac": seud.de_telefono(m.duenio.telefono),
                "tipo_identificador": "telefono",
                "telefono_cifrado": _b64(cif.cifrar(normalizar_telefono(m.duenio.telefono))),
                "nombre_cifrado": _b64(cif.cifrar(m.duenio.nombre.strip())),
            }
        else:
            propietario = {
                "identificador_hmac": seud.de_tercero(p.telefono_solicitante, m.duenio.nombre),
                "tipo_identificador": "tercero",
                "nombre_cifrado": _b64(cif.cifrar(m.duenio.nombre.strip())),
            }
        c = ln.cotizacion
        lineas.append({
            "mascota": {"nombre": m.nombre.strip(), "raza": m.raza, "temperamento": m.temperamento,
                        "propietario": propietario},
            "servicio": ln.servicio,
            "precio_estimado": str(c.precio_estimado),
            "semiamplitud": str(c.semiamplitud),
            "es_comprometido": c.es_comprometido,
            "atributos_no_declarados": list(c.atributos_no_declarados),
            "desglose": c.desglose,
        })

    payload: dict[str, Any] = {
        "clave_idempotencia": p.clave_idempotencia.strip(),
        "solicitante": solicitante,
        "origen": p.origen,
        "horario_inicio": p.inicio.isoformat(),
        "horario_fin": p.fin.isoformat(),
        "puerta_a_puerta": p.puerta_a_puerta,
        "costo_traslado": str(_dinero(p.costo_traslado, "costo_traslado")),
        "direccion_cifrada": _b64(cif.cifrar(p.direccion)) if p.direccion else None,
        "dentro_perimetro_urbano": p.dentro_perimetro_urbano,
        "tarifario_version": p.tarifario_version,
        "lineas": lineas,
        "sector": p.sector,
        "pedido_especial": p.pedido_especial,
        "requiere_revision_manual": p.requiere_revision_manual,
    }
    if p.descuento:
        payload["descuento"] = {"tipo": p.descuento.tipo, "detalle": p.descuento.detalle,
                                "monto": str(_dinero(p.descuento.monto, "descuento.monto"))}
    return payload


def registrar_cita_propuesta(conexion, propuesta: PropuestaCita,
                             seud: Seudonimizador, cif: Cifrador) -> ResultadoRegistro:
    """Registra la propuesta. Seguro de reintentar con la misma clave."""
    payload = construir_payload(propuesta, seud, cif)
    with conexion.transaction():
        fila = conexion.execute(
            "SELECT cita_id, creada FROM mia.fn_registrar_cita(%s::jsonb)",
            (json.dumps(payload, ensure_ascii=False),),
        ).fetchone()
    return ResultadoRegistro(cita_id=fila[0], creada=fila[1])


def obtener_resumen(conexion, cita_id: int) -> Optional[dict]:
    """Totales de la cita para el resumen de SCRUM-75 (sin datos personales)."""
    cur = conexion.execute("SELECT * FROM mia.v_cita_resumen WHERE cita_id = %s", (cita_id,))
    fila = cur.fetchone()
    if fila is None:
        return None
    return dict(zip([d.name for d in cur.description], fila))
