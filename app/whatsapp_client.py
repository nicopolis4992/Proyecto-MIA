"""
Cliente de WhatsApp Cloud API.

- SCRUM-84: envio de mensajes salientes.
- SCRUM-87: manejo de errores y caidas de conexion. Los errores transitorios
  (red, timeout, 429, 5xx) se reintentan con backoff exponencial. Si aun asi
  falla, quien llama decide (ver app/mensajeria.py, que encola el mensaje en
  vez de perderlo). Los errores permanentes (4xx distintos de 429: numero
  invalido, token vencido) no se reintentan porque repetirlos no los arregla.
"""

import logging
import os
import time

import httpx

GRAPH_API_VERSION = "v21.0"
MAX_INTENTOS = int(os.getenv("WHATSAPP_MAX_INTENTOS", "3"))
ESPERA_BASE_S = float(os.getenv("WHATSAPP_ESPERA_BASE_S", "1.0"))

logger = logging.getLogger("whatsapp")


class ErrorWhatsApp(RuntimeError):
    def __init__(self, mensaje: str, transitorio: bool):
        super().__init__(mensaje)
        self.transitorio = transitorio


def _credenciales() -> tuple[str, str]:
    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    if not access_token or not phone_number_id:
        raise ErrorWhatsApp(
            "Faltan WHATSAPP_ACCESS_TOKEN o WHATSAPP_PHONE_NUMBER_ID "
            "en las variables de entorno",
            transitorio=False,
        )
    return access_token, phone_number_id


def _es_transitorio(status: int) -> bool:
    return status == 429 or status >= 500


def _con_reintentos(operacion, descripcion: str):
    """Ejecuta `operacion()` reintentando solo ante errores transitorios."""
    ultimo_error: ErrorWhatsApp | None = None
    for intento in range(1, MAX_INTENTOS + 1):
        try:
            return operacion()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            ultimo_error = ErrorWhatsApp(
                f"{descripcion}: HTTP {status} {exc.response.text[:300]}",
                transitorio=_es_transitorio(status),
            )
        except httpx.TransportError as exc:  # timeout, DNS, conexion rechazada
            ultimo_error = ErrorWhatsApp(f"{descripcion}: {exc!r}", transitorio=True)

        logger.warning("Intento %d/%d fallido. %s", intento, MAX_INTENTOS, ultimo_error)
        if not ultimo_error.transitorio or intento == MAX_INTENTOS:
            break
        time.sleep(ESPERA_BASE_S * 2 ** (intento - 1))

    assert ultimo_error is not None
    raise ultimo_error


def send_text_message(to: str, body: str) -> str | None:
    """
    Envia un mensaje de texto y devuelve el id de mensaje que asigna Meta
    (wamid). Ese id permite asociar una respuesta "citada" de la propietaria
    con la cita que se le envio a aprobar (SCRUM-77).

    Lanza ErrorWhatsApp si no se pudo enviar tras los reintentos.
    """
    access_token, phone_number_id = _credenciales()
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }

    def _enviar():
        with httpx.Client(timeout=10) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            mensajes = response.json().get("messages") or [{}]
            return mensajes[0].get("id")

    return _con_reintentos(_enviar, f"Envio a {to}")


def download_media(media_id: str) -> bytes:
    """
    Descarga un archivo multimedia recibido (ej. la foto de la mascota).
    Meta entrega primero una URL temporal y luego el binario, ambos con el
    mismo token de acceso.
    """
    access_token, _ = _credenciales()
    headers = {"Authorization": f"Bearer {access_token}"}

    def _descargar():
        with httpx.Client(timeout=20) as client:
            meta = client.get(
                f"https://graph.facebook.com/{GRAPH_API_VERSION}/{media_id}",
                headers=headers,
            )
            meta.raise_for_status()
            archivo = client.get(meta.json()["url"], headers=headers)
            archivo.raise_for_status()
            return archivo.content

    return _con_reintentos(_descargar, f"Descarga de media {media_id}")
