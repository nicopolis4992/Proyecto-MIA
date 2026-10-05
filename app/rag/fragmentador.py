"""
Construccion de fragmentos para la base vectorial (insumo de SCRUM-67).

Dos fuentes:
1. Documentos markdown en app/rag/conocimiento/: cada seccion "## " es un
   fragmento autocontenido (el titulo del documento y de la seccion se
   anteponen al texto para que el embedding tenga contexto).
2. El tarifario parametrizado v2 (SCRUM-98): los precios se generan desde el
   JSON con el mismo motor que cotiza en cada indexacion. Asi el RAG y el motor de cotizacion nunca
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
    """Fragmentos de precios generados desde el tarifario v2 (SCRUM-98)."""
    from app.cotizacion.motor_cotizacion_v2 import Tarifario, precio_escenario

    tar = Tarifario.desde_archivo(ruta)
    t = tar.datos
    fuente = Path(ruta).name
    etiqueta = {"pequeno": "pequeño", "mediano": "mediano", "grande": "grande"}
    kg = {k: v["peso_kg"] for k, v in t["tamanos"].items() if not k.startswith("_")}
    grupos = [g for g in t["grupos_manto"] if not g.startswith("_")]
    nota = " El valor exacto depende del tamaño, el tipo de pelo y si tiene nudos."
    frags: list[Fragmento] = []

    for codigo, s in t["servicios"].items():
        por_tamano = []
        for tam in kg:
            precios = [precio_escenario(tar, codigo, tam, g, "sin_motas", "tranquilo")[0] for g in grupos]
            por_tamano.append(f"{etiqueta[tam]} ({kg[tam][0]:g}–{kg[tam][1]:g} kg) de "
                              f"{_usd(min(precios))} a {_usd(max(precios))}")
        texto = (
            f"Precio del {s['nombre']}. Incluye: {', '.join(s['incluye'])}. "
            f"Precio desde {_usd(s['piso'])}. Según el tamaño y el tipo de pelo, sin nudos: "
            f"{'; '.join(por_tamano)}.{nota}"
        )
        frags.append(Fragmento(f"tarifario#servicio_{codigo}", fuente, s["nombre"], texto))

    desl = t["servicios_especiales"]["deslanado"]
    precios = "; ".join(f"{etiqueta[tam]} " + (_usd(desl[tam]["precio"][0]) if desl[tam]["precio"][0] == desl[tam]["precio"][1]
                        else f"de {_usd(desl[tam]['precio'][0])} a {_usd(desl[tam]['precio'][1])}") for tam in kg)
    frags.append(Fragmento(
        "tarifario#servicio_deslanado", fuente, "Deslanado",
        f"Precio del deslanado (retiro del subpelo): {precios}. Solo aplica a perros de doble capa "
        "como husky, pug, labrador o pastor alemán; a perros de pelo que se corta con máquina "
        "(shih tzu, schnauzer, poodle) no se les hace deslanado.",
    ))

    frags.append(Fragmento(
        "tarifario#tipos_de_pelo", fuente, "Tipos de pelo",
        "Además del tamaño, el precio depende del tipo de pelo. Trabajamos cuatro tipos: "
        + "; ".join(t["grupos_manto"][g]["como_lo_describe_la_clienta"].lower() for g in grupos)
        + ". Los perros mestizos se cotizan igual, según su tamaño y cómo es su pelo.",
    ))

    rec = t["recargo_estado_manto"]
    frags.append(Fragmento(
        "tarifario#recargos", fuente, "Recargo por nudos y comportamiento",
        "Si el pelo tiene nudos se cobra un recargo por desenredo según el tamaño: "
        + "; ".join(f"{etiqueta[tam]} +{round(rec['moderado'][tam]['pct'] * 100)} % con algunos nudos y "
                    f"+{round(rec['severo'][tam]['pct'] * 100)} % si está muy enredado" for tam in kg)
        + ". El desenredo se hace siempre que el pelo se pueda recuperar; si no, se rapa. "
        "Los perros nerviosos o miedosos pueden tener un pequeño recargo.",
    ))

    frags.append(Fragmento(
        "tarifario#exclusiones", fuente, "Perros que no atendemos",
        f"No atendemos perros agresivos ni perros de más de {t['peso_max_kg']:g} kg.",
    ))

    zonas = t["traslado"]["zonas"]
    detalle = []
    for z in zonas.values():
        precio = _usd(z["precio"][0]) if z["precio"][0] == z["precio"][1] else f"de {_usd(z['precio'][0])} a {_usd(z['precio'][1])}"
        donde = ", ".join(z["sectores"]) if z["sectores"] else "sectores cercanos al local"
        detalle.append(f"{donde}: {precio}")
    frags.append(Fragmento(
        "tarifario#puerta_a_puerta", fuente, "Precio del servicio puerta a puerta",
        "Costo del servicio puerta a puerta (retiro y entrega a domicilio): " + "; ".join(detalle)
        + ". Para otros sectores el costo lo confirma la propietaria.",
    ))

    multi = t["descuentos"]["multi_mascota"]
    frags.append(Fragmento(
        "tarifario#multimascota", fuente, "Descuento por varias mascotas",
        f"Si trae {multi['minimo_mascotas']} o más mascotas en la misma cita, se descuenta "
        f"de {_usd(multi['monto_por_mascota'][0])} a {_usd(multi['monto_por_mascota'][1])} por cada una.",
    ))

    ppp = t["pico_y_placa"]
    ventanas = " y ".join(f"{a} a {b}" for a, b in ppp["ventanas"])
    frags.append(Fragmento(
        "tarifario#restriccion_vehicular", fuente, "Horarios sin servicio puerta a puerta",
        f"Por la restricción de circulación vehicular, los {ppp['dia']} no se hacen retiros a "
        f"domicilio entre {ventanas}. Fuera de esas franjas sí hay servicio puerta a puerta. "
        "Esta restricción solo afecta a los retiros a domicilio, no a las mascotas que el "
        "cliente lleva personalmente al salón.",
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
