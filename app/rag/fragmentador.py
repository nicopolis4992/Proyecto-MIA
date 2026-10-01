"""
Construccion de fragmentos para la base vectorial (insumo de SCRUM-67).

Dos fuentes:
1. Documentos markdown en app/rag/conocimiento/: cada seccion "## " es un
   fragmento autocontenido (el titulo del documento y de la seccion se
   anteponen al texto para que el embedding tenga contexto).
2. El tarifario parametrizado (SCRUM-98): los precios se generan desde el
   JSON en cada indexacion. Asi el RAG y el motor de cotizacion nunca
   pueden dar precios distintos, y un cambio de precio se propaga solo con
   re-indexar (SCRUM-70).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

DIR_CONOCIMIENTO = Path(__file__).parent / "conocimiento"


@dataclass
class Fragmento:
    id: str
    fuente: str
    titulo: str
    texto: str

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.texto.encode("utf-8")).hexdigest()[:16]


def _slug(texto: str) -> str:
    texto = texto.lower()
    for a, b in zip("áéíóúñ", "aeioun"):
        texto = texto.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "_", texto).strip("_")


def fragmentos_desde_markdown(ruta: Path) -> list[Fragmento]:
    contenido = re.sub(r"<!--.*?-->", "", ruta.read_text(encoding="utf-8"), flags=re.S)
    titulo_doc = ""
    fragmentos: list[Fragmento] = []
    seccion, lineas = None, []

    def _cerrar():
        cuerpo = " ".join(l.strip() for l in lineas if l.strip())
        if seccion and cuerpo:
            fragmentos.append(
                Fragmento(
                    id=f"{ruta.stem}#{_slug(seccion)}",
                    fuente=ruta.name,
                    titulo=seccion,
                    texto=f"{titulo_doc} — {seccion}. {cuerpo}",
                )
            )

    for linea in contenido.splitlines():
        if linea.startswith("# "):
            titulo_doc = linea[2:].strip()
        elif linea.startswith("## "):
            _cerrar()
            seccion, lineas = linea[3:].strip(), []
        else:
            lineas.append(linea)
    _cerrar()
    return fragmentos


def _usd(v: float) -> str:
    return f"USD {v:.2f}"


def fragmentos_desde_tarifario(ruta: Path) -> list[Fragmento]:
    t = json.loads(Path(ruta).read_text(encoding="utf-8"))
    fuente = Path(ruta).name
    tamanos = {x["codigo"]: x for x in t["clasificacion_tamano"]}
    nota = ""
    if t["metadata"].get("estado_validacion") != "VALIDADO":
        nota = " Estos valores son referenciales y pueden ajustarse al recibir a la mascota."

    frags: list[Fragmento] = []

    for s in t["servicios"]:
        precios = ", ".join(
            f"{tamanos[k]['etiqueta'].lower()} ({tamanos[k]['peso_kg_min']:g}–"
            f"{tamanos[k]['peso_kg_max']:g} kg) {_usd(v)}"
            for k, v in s["precio_base"].items()
        )
        duraciones = ", ".join(
            f"{tamanos[k]['etiqueta'].lower()} {v} min" for k, v in s["duracion_min"].items()
        )
        texto = (
            f"Precio del servicio {s['nombre']}. Incluye: {', '.join(s['incluye'])}. "
            f"Precio base para pelaje corto según tamaño: {precios}. "
            f"Duración aproximada: {duraciones}."
        )
        if s.get("restriccion_pelaje"):
            texto += f" Solo aplica a perros de pelaje {' o '.join(s['restriccion_pelaje'])}."
        frags.append(Fragmento(f"tarifario#servicio_{s['codigo']}", fuente, s["nombre"], texto + nota))

    def _ajuste(factor: float) -> str:
        return "sin recargo" if factor == 1 else f"+{round((factor - 1) * 100)} %"

    pelajes = ", ".join(
        f"{p['etiqueta'].lower()} {_ajuste(p['factor'])}" for p in t["clasificacion_pelaje"]
    )
    frags.append(Fragmento(
        "tarifario#pelaje", fuente, "Ajuste por tipo de pelaje",
        f"Ajuste del precio según el tipo de pelaje: {pelajes}. El ajuste se aplica sobre el precio base del servicio.",
    ))

    recargos = {r["codigo"]: r for r in t["recargos"]}
    niveles = recargos["estado_manto"]["niveles"]
    frags.append(Fragmento(
        "tarifario#recargos", fuente, "Recargos adicionales",
        "Recargos adicionales por mascota: desenredo y retiro de nudos según el estado del pelo "
        + ", ".join(f"{k.replace('_', ' ')} +{round(v * 100)} %" for k, v in niveles.items() if v)
        + f"; manejo especial por comportamiento {_usd(recargos['manejo_especial']['monto'])}; "
        f"baño medicado o antipulgas {_usd(recargos['bano_medicado']['monto'])}. "
        f"Atención el mismo día: {_usd(recargos['servicio_inmediato']['monto'])} por visita." + nota,
    ))

    zonas = recargos["puerta_a_puerta"]["valores_por_zona"]
    frags.append(Fragmento(
        "tarifario#puerta_a_puerta", fuente, "Precio del servicio puerta a puerta",
        "Costo del servicio puerta a puerta (retiro y entrega a domicilio), se cobra una vez por visita: "
        + "; ".join(f"{z['etiqueta'].lower()} (hasta {z['radio_km']} km) {_usd(z['monto'])}" for z in zonas.values())
        + "." + nota,
    ))

    escala = t["descuentos"][0]["escala"]
    frags.append(Fragmento(
        "tarifario#multimascota", fuente, "Descuento por varias mascotas",
        f"Descuento por mascota adicional en la misma cita: la segunda mascota tiene "
        f"{round(escala['2'] * 100)} % de descuento y desde la tercera {round(escala['3_o_mas'] * 100)} %, "
        "aplicado sobre el servicio base (no sobre recargos ni traslado).",
    ))

    ppp = t["reglas_operativas"]["pico_y_placa"]
    if ppp["activa"]:
        ventanas = " y ".join(f"{v['desde']} a {v['hasta']}" for v in ppp["ventanas_restringidas"])
        frags.append(Fragmento(
            "tarifario#restriccion_vehicular", fuente, "Horarios sin servicio puerta a puerta",
            f"Por la restricción de circulación vehicular, los {ppp['dia_restringido_declarado']} "
            f"no se hacen retiros a domicilio entre {ventanas}. Fuera de esas franjas sí hay "
            "servicio puerta a puerta. Esta restricción solo afecta a los retiros a domicilio, "
            "no a las mascotas que el cliente lleva personalmente al salón.",
        ))
    return frags


def todos_los_fragmentos(dir_conocimiento: Path = DIR_CONOCIMIENTO,
                         ruta_tarifario: Path | None = None) -> list[Fragmento]:
    from app.config import RUTA_TARIFARIO

    frags: list[Fragmento] = []
    for ruta in sorted(Path(dir_conocimiento).glob("*.md")):
        frags.extend(fragmentos_desde_markdown(ruta))
    frags.extend(fragmentos_desde_tarifario(ruta_tarifario or RUTA_TARIFARIO))
    ids = [f.id for f in frags]
    duplicados = {i for i in ids if ids.count(i) > 1}
    if duplicados:
        raise ValueError(f"Fragmentos con id duplicado (secciones repetidas): {duplicados}")
    return frags
