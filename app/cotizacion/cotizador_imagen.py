"""
Cotizacion a partir de la foto de la mascota.

- SCRUM-103: conecta la salida del clasificador de imagen (SCRUM-102) con el
  tarifario v2 (SCRUM-98). La foto aporta tamano, grupo de manto y estado del
  pelo; el motor devuelve el rango de precio y la duracion. Cada cotizacion
  guarda que backend y version clasificaron, con que confianza, que umbral se
  aplico y que version del tarifario se uso.
- SCRUM-104: fallback ante fotos de baja calidad o baja confianza segun
  politica_imagen.json (calidad -> pedir otra foto; una dimension dudosa ->
  se descarta y el motor la pregunta; intentos agotados -> revision manual
  de la propietaria).

La raza que la clienta haya dicho NO se reemplaza por la foto: si dijo
"shih tzu", el motor ya sabe el grupo y la foto solo aporta lo que falte.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.cotizacion.cotizador import Cotizador, texto_rango
from app.vision.calidad import evaluar_calidad

logger = logging.getLogger("cotizacion.imagen")

RUTA_POLITICA = Path(__file__).parent / "politica_imagen.json"
DIMENSIONES = ("tamano", "grupo", "estado")

CONSEJOS_FOTO = {
    "ilegible": "No pude abrir la imagen.",
    "pequena": "La imagen llegó muy pequeña.",
    "oscura": "La foto está muy oscura.",
    "sobreexpuesta": "La foto tiene demasiada luz.",
    "borrosa": "La foto salió algo movida o borrosa.",
    "no_es_perro": "No logro ver bien a su perrito en la foto.",
    "baja_confianza": "No logro distinguir bien el tamaño ni el tipo de pelo en esta foto.",
}
PEDIDO_FOTO = (
    " ¿Me podría enviar otra foto de cuerpo entero, de costado, con buena luz "
    "y no muy de lejos? Así le doy un valor más preciso."
)
ETIQUETA_TAMANO = {"pequeno": "pequeño", "mediano": "mediano", "grande": "grande"}
ETIQUETA_GRUPO = {"A_maquina": "pelo que se corta con máquina", "B_deslanado": "pelo de doble capa",
                  "C_cepillado": "pelo largo de cepillado", "D_corto": "pelo corto"}


def cargar_politica(ruta: Path = RUTA_POLITICA) -> dict:
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


@dataclass
class ResultadoFoto:
    accion: str                       # "cotizar" | "pedir_otra_foto"
    mensaje: str
    atributos: dict = field(default_factory=dict)      # dimensiones que superaron el umbral
    cotizaciones: dict = field(default_factory=dict)   # servicio -> salida de Cotizador.cotizar
    revision_manual: bool = False
    traza: dict = field(default_factory=dict)


def procesar_foto(datos: bytes, clasificador, cotizador: Cotizador, intento: int,
                  servicios: list[str] | None = None, mascota_base: dict | None = None,
                  politica: dict | None = None) -> ResultadoFoto:
    """
    `intento` es el numero de foto de esta mascota (1 = primera).
    `servicios`: servicios a cotizar. None = todo el catalogo (y el deslanado
    si el perro es de doble capa), para que la clienta vea todas las opciones.
    `mascota_base`: lo ya declarado en la conversacion (nombre, raza, estado,
    comportamiento...); la foto solo completa lo que falta.
    """
    politica = politica or cargar_politica()
    ultimo_intento = intento >= politica["max_fotos_por_mascota"]
    traza: dict = {"intento": intento, "version_politica": politica["metadata"]["version"]}
    base = dict(mascota_base or {})

    calidad = evaluar_calidad(datos, politica["calidad"])
    traza["calidad"] = asdict(calidad)
    motivo_rechazo = None if calidad.aceptable else calidad.motivo
    atributos: dict = {}

    if motivo_rechazo is None:
        c = clasificador.clasificar(datos)
        traza["clasificacion"] = asdict(c)
        umbrales = politica["umbrales_confianza"].get(c.backend, {d: 1.0 for d in DIMENSIONES})
        traza["umbrales"] = umbrales
        if not c.es_perro:
            motivo_rechazo = "no_es_perro"
        else:
            for dim in DIMENSIONES:
                valor, confianza = getattr(c, dim), getattr(c, f"confianza_{dim}")
                if valor and confianza >= umbrales.get(dim, 1.0):
                    atributos[dim] = valor
            if "tamano" not in atributos and "grupo" not in atributos:
                motivo_rechazo = "baja_confianza"

    if motivo_rechazo and not ultimo_intento:
        traza["decision"] = f"pedir_otra_foto:{motivo_rechazo}"
        logger.info("Foto rechazada (%s), intento %d", motivo_rechazo, intento)
        return ResultadoFoto("pedir_otra_foto", CONSEJOS_FOTO[motivo_rechazo] + PEDIDO_FOTO, traza=traza)

    # Se cotiza. Si hubo rechazo en el ultimo intento, se cotiza sin datos de
    # imagen (rango amplio) y la propietaria estima al aprobar.
    revision_manual = motivo_rechazo is not None
    traza["decision"] = "revision_manual" if revision_manual else "cotizar"
    # Lo declarado por la clienta tiene prioridad sobre la foto.
    mascota = {**{k: v for k, v in atributos.items() if not base.get(k)}, **base}

    if servicios is None:
        servicios = list(cotizador.datos["servicios"])
        if mascota.get("grupo") == "B_deslanado":
            servicios.append("deslanado")
    cotizaciones = {s: cotizador.cotizar([{**mascota, "servicio": s}]) for s in servicios}
    traza["version_tarifario"] = next(iter(cotizaciones.values()))["version_tarifario"]
    mensaje = _redactar(atributos, cotizaciones, cotizador, revision_manual)
    return ResultadoFoto("cotizar", mensaje, atributos, cotizaciones, revision_manual, traza)


def _redactar(atributos: dict, cotizaciones: dict, cotizador: Cotizador, revision_manual: bool) -> str:
    partes = []
    if revision_manual:
        partes.append("No logré estimar bien a su perrito por foto; la propietaria le confirmará el valor exacto.")
    else:
        rasgos = [f"tamaño {ETIQUETA_TAMANO[atributos['tamano']]}" if "tamano" in atributos else None,
                  ETIQUETA_GRUPO.get(atributos.get("grupo"))]
        rasgos = [r for r in rasgos if r]
        if rasgos:
            partes.append(f"Por la foto veo un perrito de {' y '.join(rasgos)}.")

    if len(cotizaciones) == 1:
        partes.append(next(iter(cotizaciones.values()))["mensaje_cliente"])
    else:
        for servicio, c in cotizaciones.items():
            m = c["mascotas"][0]
            if m.get("rango"):
                partes.append(f"• {cotizador.nombre_servicio(servicio)}: {texto_rango(m['rango'])}")
        pendientes = next(iter(cotizaciones.values()))["preguntas_pendientes"]
        if "estado_manto" in pendientes:
            partes.append("El valor exacto depende de si tiene nudos o el pelo enredado.")
        partes.append("¿Cuál le interesa?")
    return "\n".join(partes)
