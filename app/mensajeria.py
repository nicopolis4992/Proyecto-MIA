"""
Capa de mensajeria que usan los agentes para escribir a terceros (la
propietaria, o un cliente cuando la propietaria aprueba su cita).

Los agentes nunca llaman a whatsapp_client directamente: reciben un
`Mensajero`. Asi el mismo flujo corre en produccion (WhatsApp real), en el
simulador local (consola) y en las pruebas (captura en memoria).

SCRUM-87: si el envio falla despues de los reintentos, el mensaje se guarda
en la cola `mensajes_salientes` y `reintentar_pendientes()` lo vuelve a
intentar mas tarde. Ningun mensaje se pierde en silencio.
"""

from __future__ import annotations

import itertools
import logging
from typing import Protocol

from app.config import PROPIETARIA_WHATSAPP
from app.persistencia.repositorio import Repositorio
from app.whatsapp_client import FUERA_DE_VENTANA, ErrorWhatsApp, send_text_message

logger = logging.getLogger("mensajeria")

MAX_INTENTOS_COLA = 5


class Mensajero(Protocol):
    def enviar(self, destino: str, texto: str) -> str | None:
        """Envia texto y devuelve el id del mensaje (o None si quedo en cola)."""


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
            self.repo.marcar_mensaje(cola_id, "no_entregado", motivo)
            logger.error("Mensaje a %s NO entregado (%s)", destino, motivo)
            propietaria = PROPIETARIA_WHATSAPP
            if exc.codigo == FUERA_DE_VENTANA and propietaria and destino != propietaria:
                self.enviar(propietaria, f"⚠️ No pude enviarle este mensaje al cliente {destino} porque "
                                         f"{motivo}. Escríbele tú directamente:\n\n{texto}")
            return None


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
            repo.marcar_mensaje(m["id"], "fallido" if agotado else "pendiente", str(exc))
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

    def a(self, destino: str) -> list[str]:
        return [t for d, t, _ in self.enviados if d == destino]
