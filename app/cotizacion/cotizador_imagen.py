"""
Cotizacion a partir de la foto de la mascota.

- SCRUM-103: conecta la salida del clasificador de imagen (SCRUM-102) con el
  motor de cotizacion parametrizado (SCRUM-98). El resultado es un rango de
  precio y una duracion trazables: cada cotizacion guarda que backend y
  version clasificaron, con que confianza, que umbral se aplico y que
  version del tarifario se uso.
- SCRUM-104: fallback ante fotos de baja calidad o baja confianza segun
  politica_imagen.json (calidad -> pedir otra foto; una dimension dudosa ->
  se descarta y el motor pide el dato; intentos agotados -> revision manual
  de la propietaria).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from app.cotizacion.motor_cotizacion import ErrorTarifario, Mascota, Motor, Solicitud
from app.vision.calidad import evaluar_calidad

logger = logging.getLogger("cotizacion.imagen")

RUTA_POLITICA = Path(__file__).parent / "politica_imagen.json"

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
ETIQUETA_PELAJE = {"corto": "corto", "largo": "largo", "rizado": "rizado", "doble_capa": "de doble capa"}


def cargar_politica(ruta: Path = RUTA_POLITICA) -> dict:
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


@dataclass
class ResultadoFoto:
    accion: str                       # "cotizar" | "pedir_otra_foto"
    mensaje: str
    tamano: str | None = None         # solo si supero el umbral
    pelaje: str | None = None
    cotizaciones: dict = field(default_factory=dict)   # servicio -> salida de Motor.cotizar
    revision_manual: bool = False
    traza: dict = field(default_factory=dict)


def procesar_foto(datos: bytes, clasificador, motor: Motor, intento: int,
                  servicios: list[str], mascota_base: Mascota | None = None,
                  politica: dict | None = None) -> ResultadoFoto:
    """
    `intento` es el numero de foto de esta mascota (1 = primera).
    `servicios`: servicios a cotizar (si el cliente aun no eligio, varios).
    `mascota_base`: datos ya declarados en la conversacion (nombre, estado
    del manto, comportamiento); la foto solo completa tamano y pelaje.
    """
    politica = politica or cargar_politica()
    ultimo_intento = intento >= politica["max_fotos_por_mascota"]
    traza: dict = {"intento": intento, "version_politica": politica["metadata"]["version"]}

    calidad = evaluar_calidad(datos, politica["calidad"])
    traza["calidad"] = asdict(calidad)
    motivo_rechazo = None if calidad.aceptable else calidad.motivo
    tamano = pelaje = None

    if motivo_rechazo is None:
        c = clasificador.clasificar(datos)
        traza["clasificacion"] = asdict(c)
        umbrales = politica["umbrales_confianza"].get(c.backend, {"tamano": 1.0, "pelaje": 1.0})
        traza["umbrales"] = umbrales
        if not c.es_perro:
            motivo_rechazo = "no_es_perro"
        else:
            tamano = c.tamano if c.confianza_tamano >= umbrales["tamano"] else None
            pelaje = c.pelaje if c.confianza_pelaje >= umbrales["pelaje"] else None
            if tamano is None and pelaje is None:
                motivo_rechazo = "baja_confianza"

    if motivo_rechazo and not ultimo_intento:
        traza["decision"] = f"pedir_otra_foto:{motivo_rechazo}"
        logger.info("Foto rechazada (%s), intento %d", motivo_rechazo, intento)
        return ResultadoFoto("pedir_otra_foto", CONSEJOS_FOTO[motivo_rechazo] + PEDIDO_FOTO, traza=traza)

    # Se cotiza. Si hubo rechazo en el ultimo intento, se cotiza sin datos de
    # imagen (banda amplia) y la propietaria estima al aprobar.
    revision_manual = motivo_rechazo is not None
    traza["decision"] = "revision_manual" if revision_manual else "cotizar"
    base = mascota_base or Mascota(servicio=servicios[0])
    mascota = replace(base, tamano=tamano or base.tamano, pelaje=pelaje or base.pelaje)

    cotizaciones, no_aplica = {}, []
    for servicio in servicios:
        try:
            cotizaciones[servicio] = motor.cotizar(Solicitud(mascotas=[replace(mascota, servicio=servicio)]))
        except ErrorTarifario as exc:
            no_aplica.append(servicio)
            traza.setdefault("servicios_no_aplicables", {})[servicio] = str(exc)
    if not cotizaciones:  # ej. pidio deslanado y el pelaje es corto
        cotizaciones["bano"] = motor.cotizar(Solicitud(mascotas=[replace(mascota, servicio="bano")]))

    mensaje = _redactar(tamano, pelaje, cotizaciones, no_aplica, motor, revision_manual)
    return ResultadoFoto("cotizar", mensaje, tamano, pelaje, cotizaciones, revision_manual, traza)


def _redactar(tamano, pelaje, cotizaciones, no_aplica, motor: Motor, revision_manual: bool) -> str:
    partes = []
    if revision_manual:
        partes.append("No logré estimar bien a su perrito por foto; la propietaria le confirmará el valor exacto.")
    elif tamano and pelaje:
        partes.append(f"Por la foto veo un perrito de tamaño {ETIQUETA_TAMANO[tamano]} y pelaje {ETIQUETA_PELAJE[pelaje]}.")
    elif tamano:
        partes.append(f"Por la foto veo un perrito de tamaño {ETIQUETA_TAMANO[tamano]}.")
    elif pelaje:
        partes.append(f"Por la foto veo un perrito de pelaje {ETIQUETA_PELAJE[pelaje]}.")

    for servicio in no_aplica:
        partes.append(f"El {motor.servicios[servicio]['nombre'].lower()} solo aplica a pelaje largo o de doble capa.")

    if len(cotizaciones) == 1:
        partes.append(next(iter(cotizaciones.values()))["mensaje_sugerido"])
    else:
        for servicio, c in cotizaciones.items():
            r = c["rango_estimado"]
            valor = (f"USD {c['total_estimado']:.2f}" if c["tipo_cotizacion"] == "precio_comprometido"
                     else f"entre USD {r['minimo']:.2f} y USD {r['maximo']:.2f}")
            partes.append(f"• {motor.servicios[servicio]['nombre']}: {valor}")
        faltan = next(iter(cotizaciones.values()))["datos_faltantes"]
        if "estado_manto" in faltan:
            partes.append("El valor final depende de si tiene nudos o el pelo apelmazado.")
    return "\n".join(partes)
