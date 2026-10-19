"""
Capa de mensajeria que usan los agentes para escribir a terceros (la
propietaria, o un cliente cuando la propietaria aprueba su cita).

Los agentes nunca llaman a whatsapp_client directamente: reciben un
`Mensajero`. Asi el mismo flujo corre en produccion (WhatsApp real), en el
simulador local (consola) y en las pruebas (captura en memoria).

SCRUM-87: si el envio falla despues de los reintentos, el mensaje se guarda
en la cola `mensajes_salientes` y `reintentar_pendientes()` lo vuelve a
intentar mas tarde. Ningun mensaje se pierde en silencio.

SCRUM-86: si el destino es la propietaria y el envio falla de forma
definitiva (error permanente o cola agotada), el texto se le manda ademas
por correo (app/notificaciones/correo.py).

Regla de 24 h de Meta (error 131047): si hay plantilla configurada
(WHATSAPP_PLANTILLA_*), se envia la plantilla con un resumen corto y el
mensaje completo queda "esperando_ventana" hasta que la persona responda.
"""

from __future__ import annotations

import itertools
import logging
from typing import Protocol

from app import config
from app.notificaciones import correo
from app.persistencia.repositorio import Repositorio
from app.whatsapp_client import (FUERA_DE_VENTANA, ErrorWhatsApp, send_audio_message, send_image_message,
                                 send_location_message, send_template_message, send_text_message)

logger = logging.getLogger("mensajeria")

MAX_INTENTOS_COLA = 5


class Mensajero(Protocol):
    def enviar(self, destino: str, texto: str) -> str | None:
        """Envia texto y devuelve el id del mensaje (o None si quedo en cola)."""

    def enviar_audio(self, destino: str, datos: bytes, mime: str) -> str | None:
        """Reenvia una nota de voz. None si no se pudo (no se encola)."""

    def enviar_imagen(self, destino: str, datos: bytes, texto: str) -> str | None:
        """Envia una foto con un texto al pie."""

    def enviar_ubicacion(self, destino: str, ubicacion: dict) -> str | None:
        """Envia el pin de ubicacion del local."""


class MensajeroWhatsApp:
    def __init__(self, repo: Repositorio):
        self.repo = repo

    def enviar(self, destino: str, texto: str) -> str | None:
        try:
            return send_text_message(to=destino, body=texto)
        except ErrorWhatsApp as exc:
            motivo = exc.explicacion or str(exc)
            if exc.transitorio:
                cola_id = self.repo.encolar_mensaje(destino, texto, motivo)
                logger.error("Mensaje a %s no enviado; encolado con id %d. Motivo: %s", destino, cola_id, motivo)
                return None
            # Error permanente (ventana de 24 h, numero no permitido, token):
            # reintentar no sirve. Queda registrado como no entregado (panel) y,
            # si el destinatario era un cliente, se avisa a la propietaria para
            # que le escriba ella.
            cola_id = self.repo.encolar_mensaje(destino, texto, motivo)
            propietaria = config.PROPIETARIA_WHATSAPP
            if exc.codigo == FUERA_DE_VENTANA:
                aviso_id = self._avisar_con_plantilla(destino, texto)
                if aviso_id:
                    # El texto completo sale cuando responda (entregar_en_espera).
                    self.repo.marcar_mensaje(cola_id, "esperando_ventana", motivo + " · se envió plantilla")
                    return aviso_id
            if destino == propietaria and correo.respaldo_propietaria(texto, motivo):
                motivo += " · enviado por correo"
            self.repo.marcar_mensaje(cola_id, "no_entregado", motivo)
            logger.error("Mensaje a %s NO entregado (%s)", destino, motivo)
            if exc.codigo == FUERA_DE_VENTANA and propietaria and destino != propietaria:
                self.enviar(propietaria, f"⚠️ No pude enviarle este mensaje al cliente {destino} porque "
                                         f"{motivo}. Escríbele tú directamente:\n\n{texto}")
            return None

    def enviar_audio(self, destino: str, datos: bytes, mime: str = "audio/ogg") -> str | None:
        try:
            return send_audio_message(destino, datos, mime)
        except ErrorWhatsApp as exc:
            logger.error("No se pudo reenviar la nota de voz a %s: %s", destino, exc.explicacion or exc)
            return None

    def enviar_imagen(self, destino: str, datos: bytes, texto: str) -> str | None:
        try:
            return send_image_message(destino, datos, texto)
        except ErrorWhatsApp as exc:
            # Sin la foto, al menos le llega el texto (y queda en cola si falla).
            logger.error("No se pudo enviar la foto a %s: %s", destino, exc.explicacion or exc)
            return self.enviar(destino, texto + "\n(No pude adjuntar la foto: pídesela al cliente.)")

    def enviar_ubicacion(self, destino: str, ubicacion: dict) -> str | None:
        try:
            return send_location_message(destino, ubicacion["latitud"], ubicacion["longitud"],
                                         ubicacion.get("nombre", ""), ubicacion.get("direccion", ""))
        except ErrorWhatsApp as exc:
            logger.error("No se pudo enviar la ubicacion a %s: %s", destino, exc.explicacion or exc)
            return self.enviar(destino, texto_ubicacion(ubicacion))

    def _avisar_con_plantilla(self, destino: str, texto: str) -> str | None:
        """
        Fuera de la ventana de 24 h solo se puede enviar una plantilla aprobada
        por Meta. Se envia un aviso corto ("tiene una actualización: ...") y el
        mensaje completo queda en espera hasta que la persona responda.
        Devuelve el id del aviso: si la propietaria lo cita, se asocia a la cita.
        """
        plantilla = (config.PLANTILLA_PROPIETARIA if destino == config.PROPIETARIA_WHATSAPP
                     else config.PLANTILLA_CLIENTE)
        if not plantilla:
            return None
        try:
            return send_template_message(destino, plantilla, [resumen_corto(texto)], config.PLANTILLA_IDIOMA)
        except ErrorWhatsApp as exc:
            logger.error("Tampoco se pudo enviar la plantilla %s a %s: %s", plantilla, destino, exc)
            return None


def texto_ubicacion(ubicacion: dict) -> str:
    """La ubicacion como texto con enlace de Google Maps (demo y respaldo)."""
    lineas = [f"📍 {ubicacion.get('nombre') or 'Ubicación'}"]
    if ubicacion.get("direccion"):
        lineas.append(ubicacion["direccion"])
    lineas.append(f"https://maps.google.com/?q={ubicacion['latitud']},{ubicacion['longitud']}")
    return "\n".join(lineas)


def resumen_corto(texto: str, limite: int = 160) -> str:
    """Parametro de plantilla: una linea, sin tabulaciones ni espacios repetidos."""
    lineas = [ln.strip(" •-") for ln in texto.splitlines() if ln.strip()]
    plano = " · ".join(lineas[:3])
    plano = " ".join(plano.replace("\t", " ").split())
    return plano if len(plano) <= limite else plano[:limite - 1].rstrip() + "…"


def entregar_en_espera(repo: Repositorio, destino: str) -> int:
    """
    La persona escribio: la ventana de 24 h esta abierta otra vez y se le
    entregan los mensajes que quedaron en espera. Devuelve cuantos salieron.
    """
    entregados = 0
    for m in repo.mensajes_en_espera(destino):
        try:
            send_text_message(to=destino, body=m["cuerpo"])
            repo.marcar_mensaje(m["id"], "enviado")
            entregados += 1
        except ErrorWhatsApp as exc:
            repo.marcar_mensaje(m["id"], "esperando_ventana", str(exc))
    if entregados:
        logger.info("Entregados %d mensaje(s) en espera a %s", entregados, destino)
    return entregados


def reintentar_pendientes(repo: Repositorio) -> dict:
    """Reintenta los mensajes encolados. Pensado para correr periodicamente."""
    enviados = fallidos = 0
    for m in repo.mensajes_pendientes(MAX_INTENTOS_COLA):
        try:
            send_text_message(to=m["destino"], body=m["cuerpo"])
            repo.marcar_mensaje(m["id"], "enviado")
            enviados += 1
        except ErrorWhatsApp as exc:
            agotado = m["intentos"] + 1 >= MAX_INTENTOS_COLA or not exc.transitorio
            error = str(exc)
            if agotado and m["destino"] == config.PROPIETARIA_WHATSAPP and correo.respaldo_propietaria(
                    m["cuerpo"], exc.explicacion or error):
                error += " · enviado por correo"
            repo.marcar_mensaje(m["id"], "fallido" if agotado else "pendiente", error)
            fallidos += 1
    if enviados or fallidos:
        logger.info("Cola de salida: %d enviados, %d fallidos", enviados, fallidos)
    return {"enviados": enviados, "fallidos": fallidos}


class MensajeroMemoria:
    """Para pruebas y para el simulador: guarda lo enviado en una lista."""

    def __init__(self, eco: bool = False):
        self.enviados: list[tuple[str, str, str]] = []
        self._ids = itertools.count(1)
        self.eco = eco

    def enviar(self, destino: str, texto: str) -> str | None:
        msg_id = f"wamid.sim.{next(self._ids)}"
        self.enviados.append((destino, texto, msg_id))
        if self.eco:
            print(f"\n  >>> [a {destino}] ({msg_id})\n  {texto.replace(chr(10), chr(10) + '  ')}\n")
        return msg_id

    def enviar_audio(self, destino: str, datos: bytes, mime: str = "audio/ogg") -> str | None:
        msg_id = f"wamid.sim.{next(self._ids)}"
        self.enviados.append((destino, f"[audio {len(datos)} bytes]", msg_id))
        return msg_id

    def enviar_imagen(self, destino: str, datos: bytes, texto: str) -> str | None:
        return self.enviar(destino, f"📷 {texto}")

    def enviar_ubicacion(self, destino: str, ubicacion: dict) -> str | None:
        return self.enviar(destino, texto_ubicacion(ubicacion))

    def a(self, destino: str) -> list[str]:
        return [t for d, t, _ in self.enviados if d == destino]
