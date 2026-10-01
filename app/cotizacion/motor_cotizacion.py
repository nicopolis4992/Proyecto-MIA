# -*- coding: utf-8 -*-
"""
Proyecto MIA — Lina's Pet Salón
SCRUM-98: Motor de cotización parametrizado.

CRITERIOS DE ACEPTACIÓN CUBIERTOS
---------------------------------
  [x] Rangos de precio definidos por tamaño y tipo de pelaje
  [x] Costo adicional configurable para el servicio puerta a puerta
  [x] Soporta múltiples mascotas en una misma cita con total agregado
  [x] Valores externos al código, en tarifario_v1.json

PRINCIPIO DE DISEÑO
-------------------
No hay un solo monto escrito en este archivo. Todos los valores provienen del
JSON. Cambiar un precio es editar un archivo de configuración y versionarlo, no
tocar código ni volver a desplegar. La deuda de configuración descrita por
Sculley et al. (2015) aparece precisamente cuando esta separación no se respeta:
los valores de negocio migran al código, dejan de ser auditables y nadie sabe qué
precio estuvo vigente en qué fecha.

SALIDA
------
`cotizar()` devuelve un diccionario serializable que alimenta directamente el
campo `cotizacion_estimada` del resumen de aprobación (SCRUM-74).

Uso:
    from motor_cotizacion import Motor, Mascota, Solicitud
    motor = Motor("tarifario_v1.json")
    print(motor.cotizar(solicitud))
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any


class ErrorTarifario(ValueError):
    """Error de configuración o de solicitud inválida."""


@dataclass
class Mascota:
    """Una mascota dentro de una solicitud de cotización.

    Los campos en None representan información que el cliente NO declaró. Esa
    ausencia no se rellena con supuestos: se traduce en una banda de confianza
    más ancha y en una pregunta que el agente debe formular.
    """

    servicio: str
    nombre: str | None = None
    tamano: str | None = None
    pelaje: str | None = None
    estado_manto: str | None = None
    comportamiento_conocido: bool = False
    extras: list[str] = field(default_factory=list)


@dataclass
class Solicitud:
    mascotas: list[Mascota]
    modalidad: str = "salon"                  # salon | puerta_a_puerta
    zona: str | None = None                   # zona_1 | zona_2 | zona_3
    fecha_hora: datetime | None = None
    cliente_recurrente: bool = False
    extras_visita: list[str] = field(default_factory=list)


class Motor:
    def __init__(self, ruta_tarifario: str | Path):
        self.ruta = Path(ruta_tarifario)
        with open(self.ruta, encoding="utf-8") as fh:
            self.t: dict[str, Any] = json.load(fh)

        self.servicios = {s["codigo"]: s for s in self.t["servicios"]}
        self.recargos = {r["codigo"]: r for r in self.t["recargos"]}
        self.pelajes = {p["codigo"]: p for p in self.t["clasificacion_pelaje"]}
        self.tamanos = {x["codigo"]: x for x in self.t["clasificacion_tamano"]}
        self.globales = self.t["parametros_globales"]

    # -- utilidades ---------------------------------------------------------

    def _redondear(self, valor: float) -> float:
        paso = self.globales["redondeo_a_multiplo_de"]
        return round(round(valor / paso) * paso, 2)

    def tamano_por_peso(self, peso_kg: float) -> str:
        """Clasifica por peso. Útil cuando el cliente da el peso pero no el tamaño."""
        for t in self.t["clasificacion_tamano"]:
            if t["peso_kg_min"] <= peso_kg <= t["peso_kg_max"]:
                return t["codigo"]
        raise ErrorTarifario(f"Peso fuera de los rangos definidos: {peso_kg} kg")

    # -- cálculo por mascota ------------------------------------------------

    def _cotizar_mascota(self, m: Mascota, orden: int) -> dict:
        if m.servicio not in self.servicios:
            raise ErrorTarifario(
                f"Servicio desconocido: '{m.servicio}'. "
                f"Disponibles: {sorted(self.servicios)}"
            )
        servicio = self.servicios[m.servicio]

        # Ante tamaño no declarado se usa el escalón intermedio como estimación
        # central. No es un supuesto oculto: queda registrado en 'supuestos' y
        # penaliza explícitamente la banda de confianza.
        tamano = m.tamano or "mediano"
        if tamano not in self.tamanos:
            raise ErrorTarifario(f"Tamaño desconocido: '{tamano}'")

        pelaje = m.pelaje or "corto"
        if pelaje not in self.pelajes:
            raise ErrorTarifario(f"Tipo de pelaje desconocido: '{pelaje}'")

        restriccion = servicio.get("restriccion_pelaje")
        if restriccion and m.pelaje and m.pelaje not in restriccion:
            raise ErrorTarifario(
                f"El servicio '{servicio['nombre']}' no aplica a pelaje '{m.pelaje}'. "
                f"Aplica a: {restriccion}"
            )

        base = float(servicio["precio_base"][tamano])
        factor_pelaje = float(self.pelajes[pelaje]["factor"])
        subtotal_base = base * factor_pelaje

        lineas = [
            {
                "concepto": f"{servicio['nombre']} — tamaño {self.tamanos[tamano]['etiqueta'].lower()}",
                "valor": round(base, 2),
            },
            {
                "concepto": f"Ajuste por pelaje {self.pelajes[pelaje]['etiqueta'].lower()} (x{factor_pelaje})",
                "valor": round(subtotal_base - base, 2),
            },
        ]

        # Recargo por estado del manto (porcentaje sobre la base sin descuento)
        recargo_manto = 0.0
        nivel_manto = m.estado_manto or "sin_nudos"
        niveles = self.recargos["estado_manto"]["niveles"]
        if nivel_manto not in niveles:
            raise ErrorTarifario(
                f"Estado de manto desconocido: '{nivel_manto}'. Válidos: {sorted(niveles)}"
            )
        if niveles[nivel_manto] > 0:
            recargo_manto = subtotal_base * niveles[nivel_manto]
            lineas.append(
                {
                    "concepto": f"Desenredo — nivel {nivel_manto} "
                                f"(+{int(niveles[nivel_manto] * 100)} %)",
                    "valor": round(recargo_manto, 2),
                }
            )

        # Recargos fijos aplicables por mascota
        recargos_fijos = 0.0
        for codigo in m.extras:
            r = self.recargos.get(codigo)
            if r is None:
                raise ErrorTarifario(f"Recargo desconocido: '{codigo}'")
            if r["por"] != "mascota":
                raise ErrorTarifario(
                    f"El recargo '{codigo}' se aplica por visita, no por mascota. "
                    f"Debe declararse en Solicitud.extras_visita."
                )
            recargos_fijos += float(r["monto"])
            lineas.append({"concepto": r["nombre"], "valor": round(float(r["monto"]), 2)})

        # Descuento por mascota adicional (solo sobre el servicio base)
        descuento = 0.0
        if orden >= 2:
            escala = self.t["descuentos"][0]["escala"]
            pct = escala["2"] if orden == 2 else escala["3_o_mas"]
            descuento = subtotal_base * pct
            lineas.append(
                {
                    "concepto": f"Descuento mascota #{orden} (−{int(pct * 100)} %)",
                    "valor": -round(descuento, 2),
                }
            )

        total = subtotal_base + recargo_manto + recargos_fijos - descuento

        supuestos = []
        if m.tamano is None:
            supuestos.append("Tamaño no declarado: se estimó como mediano.")
        if m.pelaje is None:
            supuestos.append("Tipo de pelaje no declarado: se estimó como corto.")
        if m.estado_manto is None:
            supuestos.append("Estado del manto no declarado: no se aplicó recargo de desenredo.")
        if not m.comportamiento_conocido:
            supuestos.append("Comportamiento no registrado: se verifica en recepción.")

        return {
            "nombre": m.nombre or f"Mascota {orden}",
            "servicio": servicio["nombre"],
            "tamano_aplicado": tamano,
            "pelaje_aplicado": pelaje,
            "duracion_estimada_min": servicio["duracion_min"][tamano],
            "lineas": lineas,
            "subtotal": round(total, 2),
            "supuestos": supuestos,
        }

    # -- banda de confianza -------------------------------------------------

    def _incertidumbre(self, s: Solicitud) -> tuple[float, list[str]]:
        cfg = self.globales["banda_confianza"]
        u = cfg["incertidumbre_base"]
        faltantes: list[str] = []

        if any(m.tamano is None for m in s.mascotas):
            u += cfg["penalizacion_tamano_no_declarado"]
            faltantes.append("tamano")
        if any(m.pelaje is None for m in s.mascotas):
            u += cfg["penalizacion_pelaje_no_declarado"]
            faltantes.append("pelaje")
        if any(m.estado_manto is None for m in s.mascotas):
            u += cfg["penalizacion_manto_no_declarado"]
            faltantes.append("estado_manto")
        if any(not m.comportamiento_conocido for m in s.mascotas):
            u += cfg["penalizacion_comportamiento_desconocido"]
            faltantes.append("comportamiento")

        if s.cliente_recurrente:
            # Con historial de servicios previos los atributos de la mascota ya
            # están verificados presencialmente, no estimados por fotografía.
            u *= cfg["factor_cliente_recurrente"]

        return min(u, cfg["incertidumbre_maxima"]), faltantes

    # -- restricción vehicular ----------------------------------------------

    def validar_pico_y_placa(self, s: Solicitud) -> dict:
        regla = self.t["reglas_operativas"]["pico_y_placa"]
        resultado = {"aplica": False, "bloquea": False, "mensaje": None}

        if s.modalidad != "puerta_a_puerta" or not regla["activa"] or s.fecha_hora is None:
            return resultado

        dias = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
        dia = dias[s.fecha_hora.weekday()]

        if dia in ("sabado", "domingo"):
            resultado["mensaje"] = "Fin de semana: la restricción vehicular no aplica."
            return resultado

        digito = regla["ultimo_digito_placa_vehiculo"]
        if digito is not None:
            restringido = digito in regla["calendario_restriccion"].get(dia, [])
        else:
            restringido = dia == regla["dia_restringido_declarado"]

        if not restringido:
            return resultado

        resultado["aplica"] = True
        hora = s.fecha_hora.time()
        for v in regla["ventanas_restringidas"]:
            desde = time.fromisoformat(v["desde"])
            hasta = time.fromisoformat(v["hasta"])
            if desde <= hora < hasta:
                resultado["bloquea"] = True
                libres = self._ventanas_libres(regla)
                resultado["mensaje"] = (
                    f"El vehículo tiene restricción de circulación el {dia} "
                    f"entre {v['desde']} y {v['hasta']}. El retiro a domicilio no "
                    f"puede programarse en ese horario. Horarios disponibles ese "
                    f"mismo día: {libres}."
                )
                return resultado

        resultado["mensaje"] = (
            f"El {dia} hay restricción vehicular, pero el horario solicitado "
            f"({hora.strftime('%H:%M')}) está fuera de las ventanas restringidas."
        )
        return resultado

    @staticmethod
    def _ventanas_libres(regla: dict) -> str:
        v = regla["ventanas_restringidas"]
        return f"{v[0]['hasta']}–{v[1]['desde']} y después de {v[1]['hasta']}"

    # -- cotización completa ------------------------------------------------

    def cotizar(self, s: Solicitud) -> dict:
        if not s.mascotas:
            raise ErrorTarifario("La solicitud no incluye ninguna mascota.")

        detalle = [self._cotizar_mascota(m, i) for i, m in enumerate(s.mascotas, start=1)]
        subtotal_mascotas = sum(d["subtotal"] for d in detalle)

        # Recargos que se cobran una sola vez por visita
        lineas_visita = []
        total_visita = 0.0

        if s.modalidad == "puerta_a_puerta":
            r = self.recargos["puerta_a_puerta"]
            zona = s.zona or "zona_1"
            if zona not in r["valores_por_zona"]:
                raise ErrorTarifario(
                    f"Zona desconocida: '{zona}'. Válidas: {sorted(r['valores_por_zona'])}"
                )
            z = r["valores_por_zona"][zona]
            total_visita += float(z["monto"])
            lineas_visita.append(
                {
                    "concepto": f"{r['nombre']} — {z['etiqueta']}",
                    "valor": round(float(z["monto"]), 2),
                }
            )

        for codigo in s.extras_visita:
            r = self.recargos.get(codigo)
            if r is None:
                raise ErrorTarifario(f"Recargo desconocido: '{codigo}'")
            if r["por"] != "visita":
                raise ErrorTarifario(f"El recargo '{codigo}' se aplica por mascota.")
            total_visita += float(r["monto"])
            lineas_visita.append({"concepto": r["nombre"], "valor": round(float(r["monto"]), 2)})

        neto = subtotal_mascotas + total_visita

        iva_cfg = self.globales["iva"]
        iva = neto * iva_cfg["tasa"] if iva_cfg["aplica"] else 0.0
        total = self._redondear(neto + iva)

        u, faltantes = self._incertidumbre(s)
        semiamplitud = self._redondear(total * u)
        umbral = self.globales["politica_compromiso"]["umbral_precio_comprometido_usd"]
        comprometido = semiamplitud <= umbral

        duracion = sum(d["duracion_estimada_min"] for d in detalle)

        restriccion = self.validar_pico_y_placa(s)

        return {
            "version_tarifario": self.t["metadata"]["version"],
            "estado_validacion_tarifario": self.t["metadata"]["estado_validacion"],
            "moneda": self.t["metadata"]["moneda"],
            "modalidad": s.modalidad,
            "num_mascotas": len(s.mascotas),
            "detalle_por_mascota": detalle,
            "cargos_por_visita": lineas_visita,
            "subtotal_servicios": round(subtotal_mascotas, 2),
            "subtotal_visita": round(total_visita, 2),
            "iva": round(iva, 2),
            "total_estimado": total,
            "rango_estimado": {
                "minimo": self._redondear(max(total - semiamplitud, 0)),
                "maximo": self._redondear(total + semiamplitud),
                "semiamplitud": semiamplitud,
                "incertidumbre_relativa": round(u, 4),
            },
            "tipo_cotizacion": "precio_comprometido" if comprometido else "rango_estimado",
            "datos_faltantes": faltantes,
            "duracion_total_estimada_min": duracion,
            "vigencia_horas": self.t["reglas_operativas"]["vigencia_cotizacion_horas"],
            "restriccion_vehicular": restriccion,
            "requiere_aprobacion_humana": self.t["reglas_operativas"]["requiere_aprobacion_humana"],
            "mensaje_sugerido": self._mensaje(total, semiamplitud, comprometido, faltantes, restriccion),
        }

    def _mensaje(self, total, semi, comprometido, faltantes, restriccion) -> str:
        """Redacción sugerida para el cliente. El agente puede reescribirla, pero
        los montos y la condicionalidad no son negociables."""
        etiquetas = {
            "tamano": "el tamaño aproximado o el peso",
            "pelaje": "el tipo de pelaje",
            "estado_manto": "si tiene nudos o el pelo apelmazado",
            "comportamiento": "cómo se comporta durante el baño",
        }
        if comprometido:
            base = f"El valor del servicio es de USD {total:.2f}."
        else:
            base = (
                f"El valor estimado está entre USD {max(total - semi, 0):.2f} y "
                f"USD {total + semi:.2f}."
            )
            if faltantes:
                pedidos = ", ".join(etiquetas[f] for f in faltantes if f in etiquetas)
                base += f" Para darle un valor exacto necesito confirmar {pedidos}."

        if restriccion.get("bloquea"):
            base += " " + restriccion["mensaje"]
        return base


# ---------------------------------------------------------------------------
# Demostración ejecutable
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    motor = Motor(Path(__file__).parent / "tarifario_v1.json")

    casos = [
        (
            "Caso 1 — Consulta inicial mínima (el cliente solo manda una foto)",
            Solicitud(mascotas=[Mascota(servicio="bano_corte")]),
        ),
        (
            "Caso 2 — El mismo perro, con todos los datos confirmados",
            Solicitud(
                mascotas=[
                    Mascota(
                        servicio="bano_corte", nombre="Kira", tamano="pequeno",
                        pelaje="largo", estado_manto="sin_nudos",
                        comportamiento_conocido=True,
                    )
                ],
                cliente_recurrente=True,
            ),
        ),
        (
            "Caso 3 — Dos mascotas con retiro a domicilio en el valle",
            Solicitud(
                mascotas=[
                    Mascota(servicio="bano_corte", nombre="Kira", tamano="pequeno",
                            pelaje="rizado", estado_manto="moderado",
                            comportamiento_conocido=True),
                    Mascota(servicio="bano", nombre="Rocky", tamano="grande",
                            pelaje="doble_capa", estado_manto="sin_nudos",
                            comportamiento_conocido=True, extras=["bano_medicado"]),
                ],
                modalidad="puerta_a_puerta", zona="zona_3",
                fecha_hora=datetime(2026, 9, 17, 11, 0),
                cliente_recurrente=True,
            ),
        ),
        (
            "Caso 4 — Retiro a domicilio un jueves a las 07:30 (restricción activa)",
            Solicitud(
                mascotas=[Mascota(servicio="bano", tamano="mediano", pelaje="corto",
                                  estado_manto="sin_nudos", comportamiento_conocido=True)],
                modalidad="puerta_a_puerta", zona="zona_1",
                fecha_hora=datetime(2026, 9, 17, 7, 30),
            ),
        ),
    ]

    for titulo, solicitud in casos:
        print("\n" + "=" * 74)
        print(titulo)
        print("=" * 74)
        c = motor.cotizar(solicitud)
        for d in c["detalle_por_mascota"]:
            print(f"\n  {d['nombre']} — {d['servicio']} ({d['duracion_estimada_min']} min)")
            for l in d["lineas"]:
                print(f"    {l['concepto']:<52} {l['valor']:>8.2f}")
            print(f"    {'Subtotal':<52} {d['subtotal']:>8.2f}")
        for l in c["cargos_por_visita"]:
            print(f"\n    {l['concepto']:<52} {l['valor']:>8.2f}")
        print(f"\n  {'TOTAL ESTIMADO':<54} {c['total_estimado']:>8.2f}")
        r = c["rango_estimado"]
        print(f"  Rango: USD {r['minimo']:.2f} – {r['maximo']:.2f}  "
              f"(±{r['semiamplitud']:.2f} | incertidumbre {r['incertidumbre_relativa']:.1%})")
        print(f"  Tipo: {c['tipo_cotizacion']}")
        if c["datos_faltantes"]:
            print(f"  Faltan por confirmar: {', '.join(c['datos_faltantes'])}")
        if c["restriccion_vehicular"]["mensaje"]:
            print(f"  Restricción: {c['restriccion_vehicular']['mensaje']}")
        print(f"\n  Mensaje al cliente:\n    \"{c['mensaje_sugerido']}\"")
