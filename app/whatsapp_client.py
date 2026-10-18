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


# Errores de Meta que conviene reconocer por su codigo (error.code del JSON).
FUERA_DE_VENTANA = 131047     # pasaron mas de 24 h desde el ultimo mensaje del usuario
NO_PERMITIDO_EN_PRUEBAS = 131030  # el numero no esta en la lista del numero de prueba
TOKEN_INVALIDO = 190          # token vencido o revocado

EXPLICACION = {
    FUERA_DE_VENTANA: "WhatsApp no deja escribirle: pasaron más de 24 h desde su último mensaje",
    NO_PERMITIDO_EN_PRUEBAS: "ese número no está registrado en la lista del número de prueba de Meta",
    TOKEN_INVALIDO: "el token de WhatsApp venció o fue revocado (WHATSAPP_ACCESS_TOKEN)",
}


class ErrorWhatsApp(RuntimeError):
    def __init__(self, mensaje: str, transitorio: bool, codigo: int | None = None):
        super().__init__(mensaje)
        self.transitorio = transitorio
        self.codigo = codigo

    @property
    def explicacion(self) -> str | None:
        return EXPLICACION.get(self.codigo)


def _codigo_meta(response: httpx.Response) -> int | None:
    try:
        return int(response.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return None


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
            codigo = _codigo_meta(exc.response)
            ultimo_error = ErrorWhatsApp(
                f"{descripcion}: HTTP {status} {exc.response.text[:300]}",
                transitorio=_es_transitorio(status), codigo=codigo,
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
    return _enviar_payload(to, {"type": "text", "text": {"body": body}}, f"Envio a {to}")


def send_template_message(to: str, plantilla: str, parametros: list[str], idioma: str = "es") -> str | None:
    """
    Envia una plantilla aprobada por Meta. Es la unica forma de escribirle a
    alguien que no le ha escrito al bot en las ultimas 24 h (error 131047).
    Los parametros no pueden tener saltos de linea ni tabulaciones.
    """
    componentes = [{"type": "body", "parameters": [{"type": "text", "text": p} for p in parametros]}]
    return _enviar_payload(to, {"type": "template", "template": {
        "name": plantilla, "language": {"code": idioma}, "components": componentes}},
        f"Plantilla {plantilla} a {to}")


def _enviar_payload(to: str, contenido: dict, descripcion: str) -> str | None:
    access_token, phone_number_id = _credenciales()
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {"messaging_product": "whatsapp", "to": to, **contenido}

    def _enviar():
        with httpx.Client(timeout=10) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            mensajes = response.json().get("messages") or [{}]
            return mensajes[0].get("id")

    return _con_reintentos(_enviar, descripcion)


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


def send_audio_message(to: str, datos: bytes, mime: str = "audio/ogg") -> str | None:
    """
    Reenvia una nota de voz: Meta no deja reutilizar el id de un audio recibido,
    asi que se sube de nuevo (POST /media) y se envia con el id nuevo.
    """
    access_token, phone_number_id = _credenciales()
    headers = {"Authorization": f"Bearer {access_token}"}
    mime = mime.split(";")[0].strip() or "audio/ogg"

    def _subir():
        with httpx.Client(timeout=30) as client:
            r = client.post(f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/media",
                            headers=headers, data={"messaging_product": "whatsapp", "type": mime},
                            files={"file": ("nota_de_voz", datos, mime)})
            r.raise_for_status()
            return r.json()["id"]

    media_id = _con_reintentos(_subir, f"Subida de audio para {to}")
    return _enviar_payload(to, {"type": "audio", "audio": {"id": media_id}}, f"Audio a {to}")


def send_image_message(to: str, datos: bytes, caption: str = "", mime: str = "image/jpeg") -> str | None:
    """Envia una foto (p. ej. la del perro, a la propietaria): se sube a /media y se envia con su id."""
    access_token, phone_number_id = _credenciales()
    headers = {"Authorization": f"Bearer {access_token}"}

    def _subir():
        with httpx.Client(timeout=30) as client:
            r = client.post(f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/media",
                            headers=headers, data={"messaging_product": "whatsapp", "type": mime},
                            files={"file": ("foto.jpg", datos, mime)})
            r.raise_for_status()
            return r.json()["id"]

    media_id = _con_reintentos(_subir, f"Subida de foto para {to}")
    return _enviar_payload(to, {"type": "image", "image": {"id": media_id, "caption": caption[:1024]}},
                           f"Foto a {to}")
