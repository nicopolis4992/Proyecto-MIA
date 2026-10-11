"""
SCRUM-86: correo de respaldo para la propietaria.

Si un mensaje para la propietaria no sale por WhatsApp (error permanente de
Meta, o la cola de reintentos se agoto), se le manda el mismo texto por
correo para que la solicitud de cita no se quede sin atender.

Usa SMTP de la biblioteca estandar. Con Gmail: activar la verificacion en dos
pasos y crear una "contraseña de aplicacion"; con Outlook: smtp.office365.com.

    CORREO_SMTP_HOST      (por defecto smtp.gmail.com)
    CORREO_SMTP_PUERTO    (por defecto 587, STARTTLS)
    CORREO_USUARIO        cuenta que envia
    CORREO_CLAVE          contraseña de aplicacion
    CORREO_PROPIETARIA    a donde llega el respaldo

Sin estas variables el respaldo queda desactivado (solo se registra en el log).
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger("correo")


def _cfg() -> dict:
    return {
        "host": os.getenv("CORREO_SMTP_HOST", "smtp.gmail.com"),
        "puerto": int(os.getenv("CORREO_SMTP_PUERTO", "587")),
        "usuario": os.getenv("CORREO_USUARIO", ""),
        "clave": os.getenv("CORREO_CLAVE", ""),
        "destino": os.getenv("CORREO_PROPIETARIA", ""),
    }


def configurado() -> bool:
    c = _cfg()
    return bool(c["usuario"] and c["clave"] and c["destino"])


def enviar_correo(asunto: str, texto: str) -> bool:
    """Envia el correo a la propietaria. Devuelve True si salio."""
    c = _cfg()
    if not configurado():
        logger.warning("Respaldo por correo no configurado: no se envio %r", asunto)
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = asunto, c["usuario"], c["destino"]
    msg.set_content(texto)
    try:
        with smtplib.SMTP(c["host"], c["puerto"], timeout=15) as smtp:
            smtp.starttls()
            smtp.login(c["usuario"], c["clave"])
            smtp.send_message(msg)
        logger.info("Respaldo por correo enviado: %r", asunto)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("No se pudo enviar el correo de respaldo (%s): %s", asunto, exc)
        return False


def respaldo_propietaria(texto: str, motivo: str) -> bool:
    """El mensaje de WhatsApp que no le llego a la propietaria, por correo."""
    asunto = "Lina's Pet Salón: " + (texto.strip().splitlines() or ["mensaje del asistente"])[0][:80]
    cuerpo = (f"Este mensaje no se pudo entregar por WhatsApp ({motivo}).\n"
              "Para aprobar o rechazar una cita, respóndele al asistente por WhatsApp "
              "indicando el número de la cita (por ejemplo: \"listo #5\").\n\n" + texto)
    return enviar_correo(asunto, cuerpo)
