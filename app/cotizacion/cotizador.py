"""
Fachada del motor de cotizacion v2 (SCRUM-98) para los agentes.

El motor (motor_cotizacion_v2.py) trabaja con diccionarios y devuelve rangos;
los agentes necesitan ademas: el nombre legible del servicio, la siguiente
pregunta a la clienta en lenguaje simple, un texto con el valor y la
restriccion vehicular. Todo eso vive aqui para que el motor siga siendo
exactamente el de SCRUM-98 (mas sus correcciones) y los agentes no dependan
de su estructura interna.

Formato de mascota (todo opcional salvo `servicio`):
    {"nombre", "servicio", "raza", "tamano", "grupo", "estado",
     "comportamiento", "peso_kg"}
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.config import RUTA_TARIFARIO
from app.cotizacion.motor_cotizacion_v2 import (
    Tarifario,
    cotizar,
    restringido_pico_y_placa,
)

# Las preguntas que se pueden hacer a la clienta, en el orden en que el
# motor las prioriza (por impacto en USD).
ATRIBUTOS_PREGUNTABLES = ("tamano", "raza_o_grupo_manto", "estado_manto", "comportamiento")


def _usd(v: float) -> str:
    return f"USD {v:.2f}"


def texto_rango(rango: list | None) -> str | None:
    if not rango:
        return None
    lo, hi = rango
    return _usd(lo) if lo == hi else f"entre {_usd(lo)} y {_usd(hi)}"


class Cotizador:
    def __init__(self, ruta: str | Path = RUTA_TARIFARIO):
        self.t = Tarifario.desde_archivo(ruta)
        self.datos = self.t.datos

    # -- catalogo -----------------------------------------------------------

    def nombre_servicio(self, codigo: str | None) -> str:
        if codigo in self.datos["servicios"]:
            return self.datos["servicios"][codigo]["nombre"]
        if codigo == "deslanado":
            return "Deslanado"
        return codigo or "servicio por definir"

    def servicios_validos(self) -> list[str]:
        return [*self.datos["servicios"], *[k for k in self.datos["servicios_especiales"] if not k.startswith("_")]]

    def pregunta(self, atributo: str) -> str:
        return self.datos["preguntas_cliente"][atributo]

    # -- cotizacion ---------------------------------------------------------

    def cotizar(self, mascotas: list[dict], modalidad: str = "salon",
                sector: str | None = None, zona: str | None = None) -> dict:
        solicitud: dict = {"mascotas": [dict(m) for m in mascotas]}
        if modalidad == "puerta_a_puerta":
            solicitud["traslado"] = {"sector": sector, "zona": zona}
        r = cotizar(solicitud, self.t)
        for m, entrada in zip(r["mascotas"], mascotas):
            m["nombre"] = entrada.get("nombre") or m.get("nombre")
            m["servicio_nombre"] = self.nombre_servicio(m.get("servicio") or entrada.get("servicio"))
        r["modalidad"] = modalidad
        r["sector"] = sector
        r["preguntas_pendientes"] = self._preguntas(r)
        dur = r.get("duracion_visita_min")
        # Para validar el horario se usa la duracion minima: si la mascota
        # resulta mas trabajosa, la propietaria lo ajusta al aprobar.
        r["duracion_agenda_min"] = dur[0] if dur else 60
        r["mensaje_cliente"] = self.mensaje_cliente(r)
        return r

    @staticmethod
    def _preguntas(r: dict) -> list[str]:
        """Union de preguntas de todas las mascotas, ordenadas por impacto."""
        impacto: dict[str, float] = {}
        for m in r["mascotas"]:
            for p in m.get("preguntas_sugeridas", []):
                impacto[p] = max(impacto.get(p, 0), m.get("impacto_usd_por_pregunta", {}).get(p, 0))
        return sorted(impacto, key=lambda p: -impacto[p])

    def recalcular_total(self, r: dict, nuevo_traslado: float | None = None) -> dict:
        """Recalcula el total si la propietaria fija el costo del traslado."""
        if nuevo_traslado is not None:
            r["traslado"] = {**r.get("traslado", {}), "rango": [nuevo_traslado, nuevo_traslado], "resuelto": True}
        cotizables = [m for m in r["mascotas"] if m.get("rango")]
        tr = r.get("traslado", {"rango": [0, 0], "resuelto": True})
        if len(cotizables) == len([m for m in r["mascotas"] if not m.get("rechazada")]) and tr.get("resuelto"):
            d_lo, d_hi = r.get("descuento_multi_mascota", [0, 0])
            r["total"] = [sum(m["rango"][0] for m in cotizables) + tr["rango"][0] - d_hi,
                          sum(m["rango"][1] for m in cotizables) + tr["rango"][1] - d_lo]
        r["mensaje_cliente"] = self.mensaje_cliente(r)
        return r

    # -- redaccion ----------------------------------------------------------

    def mensaje_cliente(self, r: dict) -> str:
        partes: list[str] = []
        for m in r["mascotas"]:
            if m.get("rechazada"):
                partes.append(f"Lo siento mucho 🙏 {m['motivo']}")
            elif m.get("no_aplica"):
                partes.append(f"{m['motivo']} Para {m.get('nombre') or 'su perrito'} le recomiendo el "
                              f"{self.nombre_servicio(m['sugerencia_servicio'])}.")
        if r.get("total"):
            valor = texto_rango(r["total"])
            partes.append(f"El valor es de {valor}." if r["total"][0] == r["total"][1]
                          else f"El valor estimado está {valor}.")
        elif any(m.get("rango") for m in r["mascotas"]):
            subtotal = [sum(m["rango"][0] for m in r["mascotas"] if m.get("rango")),
                        sum(m["rango"][1] for m in r["mascotas"] if m.get("rango"))]
            partes.append(f"El servicio queda {texto_rango(subtotal)}")
            if r.get("traslado") and not r["traslado"].get("resuelto"):
                partes[-1] += ", más el traslado, que le confirmamos según su sector."
            else:
                partes[-1] += "."
        if r.get("total") and r["total"][0] != r["total"][1] and r["preguntas_pendientes"]:
            partes.append("El valor exacto depende del estado del pelo y se confirma al recibirlo.")
        return " ".join(partes)

    # -- restriccion vehicular (SCRUM-73) ------------------------------------

    def restringido(self, momento: datetime) -> bool:
        return restringido_pico_y_placa(momento.replace(tzinfo=None), self.t)

    def ventanas_restringidas(self) -> list[list[str]]:
        return self.datos["pico_y_placa"]["ventanas"]
