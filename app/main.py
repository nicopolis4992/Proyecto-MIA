"""
Punto de entrada de la aplicación.

Por ahora expone dos endpoints:
- GET /            -> healthcheck simple
- GET /webhook     -> verificación del webhook exigida por Meta antes de
                       activar la suscripción de WhatsApp Cloud API

El endpoint POST /webhook (recepción real de mensajes, SCRUM-83) y el envío
de mensajes salientes (SCRUM-84) se agregan en un paso posterior, una vez
que Meta valida este GET.
"""

import os

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request, Response

from app.agent import get_reply
from app.whatsapp_client import send_text_message

load_dotenv()

app = FastAPI(title="Lina's Pet Salón - Asistente WhatsApp")

# Este token lo defines tú mismo (no lo da Meta) y debe coincidir
# exactamente con el que registras en la configuración del webhook
# en Meta for Developers.
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")


@app.get("/")
def read_root():
    return {"status": "ok", "service": "linas-pet-salon-bot"}


@app.get("/webhook")
def verify_webhook(
    hub_mode: str = Query(default=None, alias="hub.mode"),
    hub_challenge: str = Query(default=None, alias="hub.challenge"),
    hub_verify_token: str = Query(default=None, alias="hub.verify_token"),
):
    """
    Meta llama a este endpoint una sola vez, al momento de configurar
    el webhook en su panel. Si el modo y el token coinciden, se debe
    devolver el 'challenge' tal cual, como texto plano.
    """
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")

    return Response(content="Verificación fallida", status_code=403)


def _extract_incoming_text_message(payload: dict):
    """
    Devuelve (remitente, texto) si el payload trae un mensaje de texto
    entrante, o None si es otro tipo de evento (estado de entrega,
    mensaje de otro tipo, etc). No lanza excepción por formato inesperado,
    solo devuelve None para que el webhook igual responda 200 a Meta.
    """
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        messages = value.get("messages")
        if not messages:
            return None

        message = messages[0]
        if message.get("type") != "text":
            return None

        return message["from"], message["text"]["body"]
    except (KeyError, IndexError, TypeError):
        return None


@app.post("/webhook")
async def receive_webhook(request: Request):
    """
    Recibe mensajes reales de WhatsApp Cloud API (SCRUM-83).

    IMPORTANTE: siempre respondemos 200 a Meta, incluso si algo falla
    procesando el mensaje. Si devolvemos un error, Meta reintenta el
    mismo webhook varias veces, lo que puede generar respuestas
    duplicadas al cliente.
    """
    payload = await request.json()

    extracted = _extract_incoming_text_message(payload)
    if extracted is None:
        return Response(status_code=200)

    sender, incoming_text = extracted

    try:
        reply_text = get_reply(incoming_text)
        send_text_message(to=sender, body=reply_text)
    except Exception as exc:  # noqa: BLE001
        # Version minima: solo logueamos. Mas adelante esto debería
        # avisar a alguien del equipo si falla repetidamente.
        print(f"Error procesando mensaje de {sender}: {exc}")

    return Response(status_code=200)
