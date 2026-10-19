"""
Construccion de fragmentos para la base vectorial (insumo de SCRUM-67).

Tres fuentes (esquema de contenido en app/rag/ESQUEMA_CONTENIDO.md, SCRUM-99):
1. Documentos markdown en app/rag/conocimiento/ (SCRUM-66): cada seccion
   "## " es un fragmento autocontenido (el titulo del documento y de la
   seccion se anteponen al texto para que el embedding tenga contexto). El
   encabezado `---` de cada documento declara sus metadatos.
2. El tarifario parametrizado v2 (SCRUM-98): los precios se generan desde el
   JSON con el mismo motor que cotiza en cada indexacion. Asi el RAG y el
   motor de cotizacion nunca pueden dar precios distintos, y un cambio de
   precio se propaga solo con re-indexar (SCRUM-70).
3. La configuracion de la agenda (horario de atencion): el mismo horario que
   usa el agente de agenda para ofrecer citas.

Metadatos por fragmento: categoria, fuente, vigente_desde y
validado_por_propietaria. Se guardan en el indice para trazabilidad y para
filtrar por categoria si hiciera falta.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DIR_CONOCIMIENTO = Path(__file__).parent / "conocimiento"


CATEGORIAS = ("negocio", "servicios", "tarifario", "cotizacion", "agenda", "horarios",
              "puerta_a_puerta", "politicas", "faq")


@dataclass
class Fragmento:
    id: str
    fuente: str
    titulo: str
    texto: str
    metadatos: dict = field(default_factory=dict)

    @property
    def hash(self) -> str:
        # Los metadatos entran al hash: si cambia la vigencia o la validacion,
        # el fragmento se vuelve a registrar en el indice.
        base = self.texto + json.dumps(self.metadatos, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def _encabezado(contenido: str) -> tuple[dict, str]:
    """Lee el bloque `---` inicial (clave: valor por linea). Devuelve (metadatos, resto)."""
    m = re.match(r"\s*---\s*\n(.*?)\n---\s*\n", contenido, flags=re.S)
    if not m:
        return {}, contenido
    meta = {}
    for linea in m.group(1).splitlines():
        if ":" in linea:
            clave, valor = linea.split(":", 1)
            meta[clave.strip()] = valor.strip()
    return meta, contenido[m.end():]


def _slug(texto: str) -> str:
    texto = texto.lower()
    for a, b in zip("áéíóúñ", "aeioun"):
        texto = texto.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "_", texto).strip("_")


def fragmentos_desde_markdown(ruta: Path) -> list[Fragmento]:
    meta, contenido = _encabezado(ruta.read_text(encoding="utf-8"))
    contenido = re.sub(r"<!--.*?-->", "", contenido, flags=re.S)
    if meta.get("categoria") and meta["categoria"] not in CATEGORIAS:
        raise ValueError(f"{ruta.name}: categoria '{meta['categoria']}' no esta en {CATEGORIAS}")
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
                    metadatos=dict(meta),
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

    # 17-oct: la propietaria aclara que el deslanado va dentro del Baño Completo.
    frags.append(Fragmento(
        "tarifario#servicio_deslanado", fuente, "Deslanado",
        f"El deslanado (retiro del subpelo) es parte del {t['servicios']['completo']['nombre']} para "
        "perros de doble capa (husky, pug, labrador, pastor alemán) y de pelo corto: no se cobra aparte. "
        "El precio es el del Baño Completo según el tamaño y el tipo de pelo.",
    ))

    frags.append(Fragmento(
        "tarifario#tipos_de_pelo", fuente, "Tipos de pelo",
        "Además del tamaño, el precio depende del tipo de pelo. Trabajamos cuatro tipos: "
        + "; ".join(t["grupos_manto"][g]["como_lo_describe_la_clienta"].lower() for g in grupos)
        + ". Los perros mestizos se cotizan igual, según su tamaño y cómo es su pelo.",
    ))

    nudos = sorted({tuple(v["monto"]) for k, v in t["recargo_estado_manto"]["moderado"].items()
                    if not k.startswith("_") and "monto" in v})
    if len(nudos) == 1:
        lo, hi = nudos[0]
        recargo_nudos = f"un recargo fijo de {_usd(lo)}" + (f" a {_usd(hi)}" if hi != lo else "")
    else:
        recargo_nudos = "un recargo según el tamaño"
    frags.append(Fragmento(
        "tarifario#recargos", fuente, "Recargo por nudos y comportamiento",
        f"Si el pelo tiene algunos nudos se suma {recargo_nudos}. Quitar motas (pelo muy enredado o "
        "apelmazado) se cobra más y fijamos el valor al ver al perro. El desenredo se hace "
        "siempre que el pelo se pueda recuperar; si no, se rapa. Los perros nerviosos o miedosos no "
        "pagan recargo, salvo casos especiales que le explicamos antes.",
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
        + ". Para otros sectores el costo se lo confirmamos.",
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
    categoria = {"servicio_": "tarifario", "tipos_de_pelo": "tarifario", "recargos": "tarifario",
                 "exclusiones": "politicas", "puerta_a_puerta": "puerta_a_puerta",
                 "multimascota": "tarifario", "restriccion_vehicular": "puerta_a_puerta"}
    for f in frags:
        sufijo = f.id.split("#", 1)[1]
        cat = next((v for k, v in categoria.items() if sufijo.startswith(k)), "tarifario")
        f.metadatos = {"categoria": cat, "fuente": f"{fuente} v{t.get('version', '')}",
                       "vigente_desde": t.get("fecha", ""), "validado_por_propietaria": "parcial"}
    return frags


_NOMBRE_DIA = {"lunes": "lunes", "martes": "martes", "miercoles": "miércoles", "jueves": "jueves",
               "viernes": "viernes", "sabado": "sábado", "domingo": "domingo"}


def fragmentos_desde_agenda(ruta: Path | None = None) -> list[Fragmento]:
    """Horario de atencion generado desde app/agenda/config_agenda.json.

    Es el mismo horario con el que el agente de agenda ofrece citas: el RAG no
    puede contestar un horario distinto del que se agenda.
    """
    from app.agenda.disponibilidad import texto_turnos_por_dia

    ruta = Path(ruta) if ruta else Path(__file__).resolve().parents[1] / "agenda" / "config_agenda.json"
    cfg = json.loads(ruta.read_text(encoding="utf-8"))
    grupos: dict[str, list[str]] = {}
    for dia, franja in cfg["horario_laboral"].items():
        clave = f"de {franja[0]} a {franja[1]}" if franja else "cerrado"
        grupos.setdefault(clave, []).append(_NOMBRE_DIA[dia])
    partes = []
    for horario, dias in grupos.items():
        lista = dias[0] if len(dias) == 1 else ", ".join(dias[:-1]) + " y " + dias[-1]
        partes.append(f"{lista}: {horario}" if horario != "cerrado" else f"{lista}: no atendemos")
    meta_cfg = cfg.get("metadata", {})
    return [Fragmento(
        "agenda#horario_de_atencion", ruta.name, "Horario de atención",
        "Horario de atención de Lina's Pet Salón: " + "; ".join(partes) + ". Las citas se agendan "
        "dentro de este horario" + (", en turnos de 2 horas: " + texto_turnos_por_dia(cfg) if cfg.get("turnos") else "")
        + ", con al menos " + str(cfg["antelacion_minima_horas"]) + " horas de anticipación.",
        metadatos={"categoria": "horarios", "fuente": meta_cfg.get("fuente_horario", ruta.name),
                   "vigente_desde": meta_cfg.get("vigente_desde", ""),
                   "validado_por_propietaria": meta_cfg.get("validado_por_propietaria", "no")},
    )]


def todos_los_fragmentos(dir_conocimiento: Path = DIR_CONOCIMIENTO,
                         ruta_tarifario: Path | None = None) -> list[Fragmento]:
    from app.config import RUTA_TARIFARIO

    frags: list[Fragmento] = []
    for ruta in sorted(Path(dir_conocimiento).glob("*.md")):
        frags.extend(fragmentos_desde_markdown(ruta))
    frags.extend(fragmentos_desde_tarifario(ruta_tarifario or RUTA_TARIFARIO))
    frags.extend(fragmentos_desde_agenda())
    ids = [f.id for f in frags]
    duplicados = {i for i in ids if ids.count(i) > 1}
    if duplicados:
        raise ValueError(f"Fragmentos con id duplicado (secciones repetidas): {duplicados}")
    return frags
