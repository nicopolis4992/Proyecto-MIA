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

from fastapi import FastAPI, Query, Response

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
