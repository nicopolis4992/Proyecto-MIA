"""
Motor de cotización v2 — Proyecto MIA (Lina's Pet Salón)

Reemplaza al motor de SCRUM-98 v1. Lee todos los valores de tarifario_v2.json
(nada de precios en el código; Sculley et al., 2015, deuda de configuración).

Diferencia central con v1: la banda de confianza ya no suma puntos fijos por
atributo no declarado. Se ENUMERAN los escenarios posibles de los atributos que la
clienta no declaró (tamaño, grupo de manto, estado del manto, comportamiento) y el
rango es [mínimo, máximo] de los precios que resultan. El precio solo se
"compromete" si la semiamplitud del rango no supera el umbral configurado.

Uso rápido:
    from motor_cotizacion_v2 import Tarifario, cotizar
    t = Tarifario.desde_archivo("tarifario_v2.json")
    r = cotizar({"mascotas": [{"nombre": "Thomas", "raza": "shih tzu",
                               "estado": "sin_motas", "comportamiento": "tranquilo",
                               "servicio": "completo"}]}, t)
"""
from __future__ import annotations

import difflib
import itertools
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any

TAMANOS = ("pequeno", "mediano", "grande")
GRUPOS = ("A_maquina", "B_deslanado", "C_cepillado", "D_corto")
ESTADOS_COTIZABLES = ("sin_motas", "moderado", "severo")
COMPORTAMIENTOS_COTIZABLES = ("tranquilo", "dificil")
SERVICIOS_CATALOGO = ("express", "basico", "completo", "premium")
SERVICIOS_ESPECIALES = ("deslanado",)


def _compactar(texto: str) -> str:
    """Forma comparable de un nombre de raza: minúsculas, sin tildes, solo letras."""
    return re.sub(r"[^a-z]", "", _normalizar(texto) or "")


def redondear(valor: float, paso: float) -> float:
    """Redondeo al múltiplo de `paso` más cercano (mitades hacia arriba)."""
    return math.floor(valor / paso + 0.5) * paso


def _normalizar(texto: str | None) -> str | None:
    if texto is None:
        return None
    reemplazos = str.maketrans("áéíóúñÁÉÍÓÚÑ", "aeiounAEIOUN")
    return texto.strip().lower().translate(reemplazos)


@dataclass
class Tarifario:
    datos: dict[str, Any]

    @classmethod
    def desde_archivo(cls, ruta: str | Path) -> "Tarifario":
        with open(ruta, encoding="utf-8") as f:
            return cls(json.load(f))

    # --- accesos ---------------------------------------------------------
    @property
    def paso(self) -> float:
        return self.datos["redondeo"]

    @property
    def umbral(self) -> float:
        return self.datos["banda_confianza"]["umbral_semiamplitud_comprometido"]

    def raza(self, nombre: str | None) -> dict | None:
        resuelta = self.resolver_raza(nombre)
        return resuelta[1] if resuelta else None

    def _indice_razas(self) -> dict[str, str]:
        """forma compacta (sin espacios, guiones ni tildes) -> clave de raza."""
        if not hasattr(self, "_cache_razas"):
            indice = {}
            for raza, info in self.datos["razas"].items():
                if raza.startswith("_"):
                    continue
                for forma in [raza, *info.get("alias", [])]:
                    indice[_compactar(forma)] = raza
            self._cache_razas = indice
        return self._cache_razas

    def resolver_raza(self, nombre: str | None) -> tuple[str, dict, str] | None:
        """Devuelve (clave, info, metodo) o None. metodo: exacto | alias | aproximado.

        Tolera errores de tipeo ("shitsu" -> "shih tzu") con difflib. Si nada
        supera el umbral, la raza queda desconocida y el motor pregunta tamaño y
        pelo: nunca adivina una raza que no reconoce.
        """
        if not nombre or not _compactar(nombre):
            return None
        indice = self._indice_razas()
        forma = _compactar(nombre)
        if forma in indice:
            clave = indice[forma]
            metodo = "exacto" if _compactar(clave) == forma else "alias"
            return clave, self.datos["razas"][clave], metodo
        umbral = self.datos.get("umbral_similitud_raza", 0.8)
        cercanas = difflib.get_close_matches(forma, list(indice), n=1, cutoff=umbral)
        if cercanas:
            clave = indice[cercanas[0]]
            return clave, self.datos["razas"][clave], "aproximado"
        return None

    def resolver_razas(self, raza: str | list | None) -> tuple[list[tuple[str | None, dict]], list[str]]:
        """Interpreta la raza declarada, incluyendo cruces y mestizos.

        - "schnauzer con poodle", "cruce de X y Y", ["X", "Y"] -> ambas razas.
        - "mestizo de rottweiler" -> rottweiler como raza predominante (con aviso).
        Una parte no reconocida se devuelve como (None, {}): deja abiertos el
        tamaño y el grupo en vez de suponerlos.
        """
        if not raza:
            return [], []
        avisos: list[str] = []
        if isinstance(raza, (list, tuple)):
            partes = [str(r) for r in raza]
        else:
            texto = _normalizar(str(raza))
            predominante = re.match(r"^(mestiz[oa]|cruce|cruzad[oa]|mezcla)\s+(de|con)\s+(.+)$", texto)
            if predominante:
                texto = predominante.group(3)
                avisos.append(f"'{raza}': se cotiza con la raza predominante; confirmar en recepción.")
            partes = [x for x in re.split(r"\s+(?:con|x|y|e)\s+|/|,|\+", texto) if x.strip()]
        resueltas: list[tuple[str | None, dict]] = []
        vistas: set[str] = set()
        for parte in partes:
            r = self.resolver_raza(parte)
            if r is None:
                avisos.append(f"Raza '{parte.strip()}' no reconocida: se pregunta tamaño y pelo.")
                resueltas.append((None, {}))
                continue
            clave, info, metodo = r
            if metodo == "aproximado":
                avisos.append(f"'{parte.strip()}' se interpretó como '{clave}'.")
            if clave not in vistas:
                vistas.add(clave)
                resueltas.append((clave, info))
        return resueltas, avisos

    def factor(self, tamano: str, grupo: str) -> float:
        return self.datos["factor_tamano_grupo"][tamano][grupo]["factor"]

    def piso(self, servicio: str) -> float:
        return self.datos["servicios"][servicio]["piso"]

    def recargo_estado(self, estado: str, tamano: str) -> float:
        valor = self.datos["recargo_estado_manto"][estado][tamano]
        return valor if isinstance(valor, (int, float)) else valor["pct"]

    def recargo_comportamiento(self, comportamiento: str) -> tuple[float, float]:
        lo, hi = self.datos["recargo_comportamiento"][comportamiento]["pct"]
        return lo, hi

    def duracion(self, servicio: str, tamano: str) -> tuple[int, int]:
        lo, hi = self.datos["duracion_min"][servicio][tamano]
        return lo, hi

    def duracion_extra_severo(self, tamano: str) -> int:
        return self.datos["duracion_min"]["extra_estado_severo"][tamano]


# --------------------------------------------------------------------------
# Precio de un escenario completamente determinado
# --------------------------------------------------------------------------
def precio_escenario(t: Tarifario, servicio: str, tamano: str, grupo: str,
                     estado: str, comportamiento: str) -> tuple[float, float, dict]:
    """Devuelve (mínimo, máximo, desglose) para un escenario sin incógnitas.

    El mínimo y el máximo solo difieren por rangos que la propia tarifa declara
    (servicios especiales con precio en rango, recargo de comportamiento pendiente).
    """
    if servicio in SERVICIOS_ESPECIALES:
        base_lo, base_hi = t.datos["servicios_especiales"][servicio][tamano]["precio"]
        origen_base = f"{servicio} {tamano}"
    else:
        base_lo = base_hi = t.piso(servicio) * t.factor(tamano, grupo)
        origen_base = f"piso {servicio} {t.piso(servicio)} x factor {tamano}/{grupo} {t.factor(tamano, grupo)}"

    pct_estado = t.recargo_estado(estado, tamano)
    pc_lo, pc_hi = t.recargo_comportamiento(comportamiento)

    lo = redondear(base_lo * (1 + pct_estado) * (1 + pc_lo), t.paso)
    hi = redondear(base_hi * (1 + pct_estado) * (1 + pc_hi), t.paso)
    desglose = {
        "base": origen_base,
        "recargo_estado_pct": pct_estado,
        "recargo_comportamiento_pct": [pc_lo, pc_hi],
    }
    return lo, hi, desglose


# --------------------------------------------------------------------------
# Cotización de una mascota con atributos posiblemente no declarados
# --------------------------------------------------------------------------
def _candidatos(t: Tarifario, m: dict) -> tuple[dict[str, list[str]], list[str]]:
    """Valores posibles de cada atributo y lista de atributos no declarados.

    Con varias razas (cruce) se toma la unión de sus valores; si alguna no
    define el atributo (o no se reconoció), el atributo queda abierto.
    """
    razas, _ = t.resolver_razas(m.get("raza"))
    faltantes = []

    def _desde_razas(campo: str) -> list[str] | None:
        if not razas or any(not info.get(campo) for _, info in razas):
            return None
        return sorted({info[campo] for _, info in razas})

    if m.get("tamano"):
        tamanos = [m["tamano"]]
    elif _desde_razas("tamano"):
        tamanos = _desde_razas("tamano")
    else:
        tamanos = list(TAMANOS)
        faltantes.append("tamano")

    if m.get("grupo"):
        grupos = [m["grupo"]]
    elif _desde_razas("grupo"):
        grupos = _desde_razas("grupo")
    else:
        grupos = list(GRUPOS)
        faltantes.append("raza_o_grupo_manto")

    if m.get("estado"):
        estados = [m["estado"]]
    else:
        estados = list(ESTADOS_COTIZABLES)
        faltantes.append("estado_manto")

    if m.get("comportamiento"):
        comportamientos = [m["comportamiento"]]
    else:
        comportamientos = list(COMPORTAMIENTOS_COTIZABLES)
        faltantes.append("comportamiento")

    return ({"tamano": tamanos, "grupo": grupos, "estado": estados,
             "comportamiento": comportamientos}, faltantes)


def _rechazo(t: Tarifario, m: dict) -> str | None:
    peso = m.get("peso_kg")
    limite = t.datos["peso_max_kg"]
    if peso is not None and peso > limite:
        return f"Peso mayor a {limite} kg: el salón no atiende perros de ese tamaño."
    if m.get("comportamiento") == "agresivo_declarado":
        return "El dueño declara que el perro es agresivo: el salón no lo atiende."
    return None


VALIDOS = {
    "tamano": TAMANOS,
    "grupo": GRUPOS,
    "estado": ESTADOS_COTIZABLES + ("no_recuperable",),
    "comportamiento": COMPORTAMIENTOS_COTIZABLES + ("agresivo_declarado",),
    "servicio": SERVICIOS_CATALOGO + SERVICIOS_ESPECIALES,
}


def normalizar_entrada(t: Tarifario, m: dict) -> tuple[dict, list[str]]:
    """Traduce sinónimos a valores válidos y descarta lo irreconocible.

    Un valor desconocido (ej. estado "regular") no rompe el motor: se trata
    como no declarado, lo que ensancha el rango y genera la pregunta, y se
    deja un aviso para trazabilidad.
    """
    equivalencias = t.datos.get("equivalencias", {})
    limpio, avisos = dict(m), []
    for campo, validos in VALIDOS.items():
        valor = m.get(campo)
        if valor is None or valor in validos:
            continue
        clave = _normalizar(str(valor))
        tabla = {_normalizar(k): v for k, v in equivalencias.get(campo, {}).items()
                 if not k.startswith("_")}
        if clave in validos:
            limpio[campo] = clave
        elif clave.replace(" ", "_") in validos:
            limpio[campo] = clave.replace(" ", "_")
        elif clave in tabla:
            limpio[campo] = tabla[clave]
        else:
            limpio[campo] = None
            avisos.append(f"Valor '{valor}' no reconocido para {campo}: se trata como no declarado.")
    peso = m.get("peso_kg")
    if peso is not None:
        try:
            limpio["peso_kg"] = float(peso)
        except (TypeError, ValueError):
            limpio["peso_kg"] = None
            avisos.append(f"Peso '{peso}' no reconocido: se ignora.")
    return limpio, avisos


def cotizar_mascota(t: Tarifario, m: dict) -> dict:
    m, avisos = normalizar_entrada(t, m)
    avisos += t.resolver_razas(m.get("raza"))[1]
    resultado = _cotizar_mascota(t, m)
    if avisos:
        resultado["avisos"] = avisos
    return resultado


def _cotizar_mascota(t: Tarifario, m: dict) -> dict:
    nombre = m.get("nombre", "mascota")
    motivo = _rechazo(t, m)
    if motivo:
        return {"nombre": nombre, "rechazada": True, "motivo": motivo}

    servicio = m.get("servicio")
    if servicio not in SERVICIOS_CATALOGO + SERVICIOS_ESPECIALES:
        return {"nombre": nombre, "rechazada": False, "requiere": ["servicio"],
                "comprometido": False, "rango": None}

    if m.get("estado") == "no_recuperable":
        return {"nombre": nombre, "rechazada": False, "comprometido": False, "rango": None,
                "requiere": ["decision_propietaria"],
                "nota": t.datos["recargo_estado_manto"]["no_recuperable"]["accion"]}

    if m.get("tamano") is None and m.get("peso_kg") is not None:
        # Se compara solo contra el limite superior, de menor a mayor: un peso
        # entre dos rangos (ej. 9.005 kg) cae en el tamano siguiente en vez de
        # quedar sin tamano.
        rangos = sorted(((info["peso_kg"][1], tam) for tam, info in t.datos["tamanos"].items()
                         if not tam.startswith("_")))
        for hi_kg, tam in rangos:
            if m["peso_kg"] <= hi_kg:
                m = {**m, "tamano": tam}
                break

    cand, faltantes = _candidatos(t, m)
    if servicio in SERVICIOS_ESPECIALES:
        aplicables = t.datos["servicios_especiales"][servicio]["grupos_aplicables"]
        posibles = [g for g in cand["grupo"] if g in aplicables]
        if not posibles:
            # El grupo es conocido y no admite el servicio (ej. deslanado a un
            # shih tzu, que es de máquina). Antes se cotizaba igual; ahora se
            # informa y se sugiere el servicio de catálogo equivalente.
            return {"nombre": nombre, "rechazada": False, "no_aplica": True,
                    "comprometido": False, "rango": None, "requiere": ["cambiar_servicio"],
                    "servicio": servicio, "sugerencia_servicio": "completo",
                    "motivo": f"El {servicio} solo aplica a perros de doble capa."}
        cand["grupo"] = posibles

    escenarios = []
    for tam, gru, est, com in itertools.product(cand["tamano"], cand["grupo"],
                                                cand["estado"], cand["comportamiento"]):
        lo, hi, des = precio_escenario(t, servicio, tam, gru, est, com)
        escenarios.append({"tamano": tam, "grupo": gru, "estado": est,
                           "comportamiento": com, "min": lo, "max": hi, "desglose": des})

    pmin = min(e["min"] for e in escenarios)
    pmax = max(e["max"] for e in escenarios)

    # Cuánto ensancha cada atributo faltante: rango del precio al variar solo ese
    # atributo, con los demás faltantes fijos en su escenario más barato.
    impacto = {}
    mas_barato = min(escenarios, key=lambda e: e["min"])
    clave = {"tamano": "tamano", "raza_o_grupo_manto": "grupo",
             "estado_manto": "estado", "comportamiento": "comportamiento"}
    for f in faltantes:
        k = clave[f]
        sub = [e for e in escenarios
               if all(e[o] == mas_barato[o] for o in ("tamano", "grupo", "estado", "comportamiento") if o != k)]
        impacto[f] = max(e["max"] for e in sub) - min(e["min"] for e in sub)
    preguntas = sorted(faltantes, key=lambda f: -impacto[f])

    # Duración (minutos)
    servicio_dur = servicio
    dur_lo = min(t.duracion(servicio_dur, e["tamano"])[0] for e in escenarios)
    dur_hi = max(t.duracion(servicio_dur, e["tamano"])[1]
                 + (t.duracion_extra_severo(e["tamano"]) if e["estado"] == "severo" else 0)
                 for e in escenarios)

    semi = (pmax - pmin) / 2
    determinado = len(escenarios) == 1
    resultado = {
        "nombre": nombre,
        "rechazada": False,
        "servicio": servicio,
        "rango": [pmin, pmax],
        "semiamplitud": semi,
        "comprometido": semi <= t.umbral,
        "preguntas_sugeridas": preguntas,
        "impacto_usd_por_pregunta": impacto,
        "duracion_min": [dur_lo, dur_hi],
        "escenarios_evaluados": len(escenarios),
    }
    if determinado:
        resultado["desglose"] = escenarios[0]["desglose"]
    if m.get("comportamiento") == "dificil":
        resultado["nota"] = "Recargo por comportamiento pendiente de la propietaria."
    return resultado


# --------------------------------------------------------------------------
# Cotización de una visita (varias mascotas + traslado + descuentos)
# --------------------------------------------------------------------------
def _traslado(t: Tarifario, pedido: dict | None) -> dict:
    if not pedido:
        return {"rango": [0, 0], "resuelto": True}
    zonas = t.datos["traslado"]["zonas"]
    zona = pedido.get("zona")
    if zona is None and pedido.get("sector"):
        s = _normalizar(pedido["sector"])
        for clave_zona, z in zonas.items():
            if any(_normalizar(x) == s for x in z["sectores"]):
                zona = clave_zona
                break
    if zona not in zonas:
        return {"rango": None, "resuelto": False,
                "accion": t.datos["traslado"]["fuera_de_zona"]["accion"]}
    lo, hi = zonas[zona]["precio"]
    return {"rango": [lo, hi], "resuelto": True, "zona": zona}


def cotizar(solicitud: dict, t: Tarifario) -> dict:
    mascotas = [cotizar_mascota(t, m) for m in solicitud.get("mascotas", [])]
    aceptadas = [m for m in mascotas if not m.get("rechazada")]
    cotizables = [m for m in aceptadas if m.get("rango")]

    traslado = _traslado(t, solicitud.get("traslado"))

    desc = t.datos["descuentos"]["multi_mascota"]
    desc_lo = desc_hi = 0.0
    if len(aceptadas) >= desc["minimo_mascotas"]:
        d_lo, d_hi = desc["monto_por_mascota"]
        desc_lo, desc_hi = d_lo * len(aceptadas), d_hi * len(aceptadas)

    completo = len(cotizables) == len(aceptadas) and traslado["resuelto"]
    total = None
    if completo and aceptadas:
        tmin = sum(m["rango"][0] for m in cotizables) + traslado["rango"][0] - desc_hi
        tmax = sum(m["rango"][1] for m in cotizables) + traslado["rango"][1] - desc_lo
        total = [tmin, tmax]

    iva = t.datos["iva"]
    avisos = []
    if iva["regimen"] is None:
        avisos.append("iva_pendiente: no se suma IVA hasta confirmar el régimen RIMPE.")
    if solicitud.get("pide_descuento_fidelidad"):
        avisos.append("La clienta pide descuento de fidelidad (USD 1–2): lo decide la propietaria en la aprobación.")
    if len(aceptadas) >= 2 and solicitud.get("traslado"):
        avisos.append("Traslado cobrado una vez por visita: SUPUESTO pendiente de confirmar.")

    comprometido = (total is not None and all(m["comprometido"] for m in cotizables)
                    and (total[1] - total[0]) / 2 <= t.umbral)
    dur = None
    if cotizables:
        dur = [sum(m["duracion_min"][0] for m in cotizables),
               sum(m["duracion_min"][1] for m in cotizables)]

    return {
        "version_tarifario": t.datos["version"],
        "mascotas": mascotas,
        "traslado": traslado,
        "descuento_multi_mascota": [desc_lo, desc_hi],
        "total": total,
        "comprometido": comprometido,
        "duracion_visita_min": dur,
        "avisos": avisos,
    }


# --------------------------------------------------------------------------
# Restricción vehicular (SCRUM-73)
# --------------------------------------------------------------------------
def restringido_pico_y_placa(momento: datetime, t: Tarifario,
                             feriados: set | None = None) -> bool:
    """True si el vehículo del puerta a puerta no puede circular en ese momento."""
    pyp = t.datos["pico_y_placa"]
    dias = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4}
    if momento.weekday() != dias[pyp["dia"]]:
        return False
    if feriados and momento.date() in feriados:
        return False
    hora = momento.time()
    for ini, fin in pyp["ventanas"]:
        h_ini = time.fromisoformat(ini)
        h_fin = time.fromisoformat(fin)
        if h_ini <= hora < h_fin:
            return True
    return False


if __name__ == "__main__":
    import pprint
    tarifa = Tarifario.desde_archivo(Path(__file__).with_name("tarifario_v2.json"))
    pprint.pprint(cotizar({"mascotas": [{"nombre": "solo foto", "servicio": "completo"}]}, tarifa))
