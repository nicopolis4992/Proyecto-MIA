"""
Envio de mensajes salientes por WhatsApp Cloud API (SCRUM-84).
"""

import os

import httpx

GRAPH_API_VERSION = "v21.0"


def send_text_message(to: str, body: str) -> None:
    """
    Envia un mensaje de texto al numero `to` usando el numero de negocio
    configurado en WHATSAPP_PHONE_NUMBER_ID.

    Lanza una excepcion si falta configuracion o si Meta responde con error,
    para que quien llame decida como manejarlo (loguear, reintentar, etc).
    """
    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

    if not access_token or not phone_number_id:
        raise RuntimeError(
            "Faltan WHATSAPP_ACCESS_TOKEN o WHATSAPP_PHONE_NUMBER_ID "
            "en las variables de entorno"
        )

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }

    with httpx.Client(timeout=10) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
