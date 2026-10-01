"""
Punto de entrada de la aplicación.

- GET /            -> healthcheck simple
- GET /webhook     -> verificación del webhook exigida por Meta
- POST /webhook    -> recepción de mensajes (SCRUM-83): texto e imágenes
- POST /admin/reintentar -> fuerza el reintento de la cola de salida (SCRUM-87)

El procesamiento del mensaje (LLM, clasificación de imagen) puede tardar
varios segundos, así que se hace en segundo plano: Meta recibe el 200 de
inmediato y no reintenta el webhook por timeout.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, Query, Request, Response

from app.agent import procesar_mensaje
from app.mensajeria import MensajeroWhatsApp, reintentar_pendientes
from app.persistencia.repositorio import obtener_repositorio
from app.whatsapp_client import download_media

load_dotenv()

logger = logging.getLogger("main")

# Este token lo defines tú mismo (no lo da Meta) y debe coincidir
# exactamente con el que registras en la configuración del webhook
# en Meta for Developers.
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
INTERVALO_COLA_S = int(os.getenv("COLA_INTERVALO_S", "60"))


async def _bucle_cola_salida():
    """SCRUM-87: reintenta periódicamente los mensajes que no salieron."""
    while True:
        await asyncio.sleep(INTERVALO_COLA_S)
        try:
            await asyncio.to_thread(reintentar_pendientes, obtener_repositorio())
        except Exception:  # noqa: BLE001
            logger.exception("Fallo reintentando la cola de salida")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    tarea = asyncio.create_task(_bucle_cola_salida())
    yield
    tarea.cancel()


app = FastAPI(title="Lina's Pet Salón - Asistente WhatsApp", lifespan=lifespan)


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


def _extract_incoming_message(payload: dict):
    """
    Devuelve un dict {id, from, tipo, texto, media_id, id_citado} si el
    payload trae un mensaje de texto o imagen, o None para cualquier otro
    evento (estados de entrega, audios, etc). No lanza excepción por formato
    inesperado, para que el webhook igual responda 200 a Meta.
    """
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        messages = value.get("messages")
        if not messages:
            return None

        message = messages[0]
        tipo = message.get("type")
        base = {
            "id": message.get("id"),
            "from": message["from"],
            "tipo": tipo,
            "id_citado": (message.get("context") or {}).get("id"),
        }
        if tipo == "text":
            return {**base, "texto": message["text"]["body"], "media_id": None}
        if tipo == "image":
            return {**base, "texto": message["image"].get("caption", ""),
                    "media_id": message["image"]["id"]}
        return {**base, "texto": None, "media_id": None}
    except (KeyError, IndexError, TypeError):
        return None


def _procesar(entrante: dict) -> None:
    repo = obtener_repositorio()
    mensajero = MensajeroWhatsApp(repo)
    sender = entrante["from"]
    try:
        if entrante["tipo"] not in ("text", "image"):
            mensajero.enviar(sender, "Por ahora solo puedo leer mensajes de texto y fotos 🙏")
            return
        imagen = download_media(entrante["media_id"]) if entrante["media_id"] else None
        reply_text = procesar_mensaje(sender, entrante["texto"] or "", imagen, entrante["id_citado"])
        if reply_text:
            mensajero.enviar(sender, reply_text)
    except Exception:  # noqa: BLE001
        logger.exception("Error procesando mensaje de %s", sender)


@app.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Recibe mensajes reales de WhatsApp Cloud API (SCRUM-83).

    IMPORTANTE: siempre respondemos 200 a Meta, incluso si algo falla
    procesando el mensaje. Si devolvemos un error, Meta reintenta el
    mismo webhook varias veces, lo que puede generar respuestas
    duplicadas al cliente. Por la misma razón se deduplica por id.
    """
    try:
        payload = await request.json()
    except ValueError:
        return Response(status_code=200)

    entrante = _extract_incoming_message(payload)
    if entrante is None:
        return Response(status_code=200)

    if entrante["id"] and not obtener_repositorio().marcar_procesado(entrante["id"]):
        logger.info("Webhook duplicado ignorado: %s", entrante["id"])
        return Response(status_code=200)

    background_tasks.add_task(_procesar, entrante)
    return Response(status_code=200)


@app.post("/admin/reintentar")
def forzar_reintento(x_admin_token: str = Header(default="")):
    if not VERIFY_TOKEN or x_admin_token != VERIFY_TOKEN:
        return Response(status_code=403)
    return reintentar_pendientes(obtener_repositorio())
