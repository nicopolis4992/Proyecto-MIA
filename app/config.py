"""
Configuracion compartida del backend.

Todo lo que depende del entorno (modelos, telefonos, rutas) se lee aqui una
sola vez para que los modulos de agentes no consulten os.getenv por su cuenta.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RAIZ_APP = Path(__file__).resolve().parent

# Modelos de Gemini (ver techContext: Flash-Lite por costo).
MODELO_LLM = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
MODELO_VISION = os.getenv("GEMINI_VISION_MODEL", MODELO_LLM)
MODELO_EMBEDDINGS = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
DIMENSION_EMBEDDINGS = int(os.getenv("GEMINI_EMBED_DIM", "768"))

# Ecuador continental no tiene horario de verano: UTC-5 fijo. Se evita
# zoneinfo porque en Windows requiere el paquete tzdata.
ZONA_HORARIA = timezone(timedelta(hours=-5), name="America/Guayaquil")

# Numero de WhatsApp de la propietaria (formato internacional sin '+',
# ej. 593999999999). Los mensajes de este numero se tratan como respuestas
# de aprobacion (SCRUM-77), nunca como mensajes de cliente.
PROPIETARIA_WHATSAPP = os.getenv("PROPIETARIA_WHATSAPP", "")

# Base SQLite provisional mientras el esquema de Supabase (SCRUM-74) no
# este disponible. En Railway el disco es efimero: sirve para el prototipo.
RUTA_DB = os.getenv("MIA_DB_PATH", str(RAIZ_APP.parent / "data" / "mia.sqlite3"))

RUTA_TARIFARIO = RAIZ_APP / "cotizacion" / "tarifario_v1.json"


def ahora() -> datetime:
    return datetime.now(ZONA_HORARIA)


def crear_cliente_gemini():
    """
    Cliente de Gemini con reintentos ante 429/5xx. En pruebas del 30-sep el
    API devolvio 503 UNAVAILABLE de forma intermitente; sin reintentos eso
    se traduce en clientes sin respuesta.
    """
    from google import genai
    from google.genai import types

    return genai.Client(
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(
                attempts=5, initial_delay=1.0, max_delay=8.0,
                http_status_codes=[429, 500, 502, 503, 504],
            )
        )
    )
