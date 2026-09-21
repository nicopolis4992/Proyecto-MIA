"""
nlu_extractor.py

Cubre:
- SCRUM-60: Clasificar intencion del mensaje
- SCRUM-61: Extraer entidades relevantes del mensaje

Estrategia: una sola llamada a Gemini con salida estructurada (JSON schema)
que devuelve intencion + entidades + confianza en un mismo objeto. Esto
evita hacer dos llamadas separadas al LLM y es justo lo que SCRUM-65 espera
consumir para enrutar en el orquestador.

Requiere: pip install google-genai
"""

import json
import logging
from dataclasses import dataclass, field

from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nlu")

MODEL = "gemini-3.5-flash-lite"

# Las 3 intenciones definidas en el alcance del proyecto (ver Alternativa 1
# de la propuesta): agendar cita, consultar servicio/producto, consulta general.
INTENCIONES_VALIDAS = ["agendar", "consultar", "general"]

# Esquema de salida estructurada que Gemini debe respetar.
NLU_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "intencion": types.Schema(
            type=types.Type.STRING,
            enum=INTENCIONES_VALIDAS,
            description="Intencion principal del mensaje del cliente.",
        ),
        "confianza": types.Schema(
            type=types.Type.NUMBER,
            description="Confianza de la clasificacion, entre 0 y 1.",
        ),
        "entidades": types.Schema(
            type=types.Type.OBJECT,
            properties={
                "servicio_mencionado": types.Schema(
                    type=types.Type.STRING,
                    nullable=True,
                    description="Servicio que el cliente menciona explicitamente "
                    "(ej. 'bano', 'corte', 'grooming completo'). Null si no se menciona.",
                ),
                "fecha_hora_sugerida": types.Schema(
                    type=types.Type.STRING,
                    nullable=True,
                    description="Fecha u hora relativa mencionada por el cliente, "
                    "normalizada en texto (ej. 'manana 3pm', 'jueves proximo'). "
                    "Null si no se menciona.",
                ),
                "tipo_mascota": types.Schema(
                    type=types.Type.STRING,
                    nullable=True,
                    description="Tipo o tamano aproximado de la mascota si se menciona. Null si no aplica.",
                ),
            },
            required=["servicio_mencionado", "fecha_hora_sugerida", "tipo_mascota"],
        ),
    },
    required=["intencion", "confianza", "entidades"],
)

SYSTEM_PROMPT = """Eres el modulo de comprension de lenguaje natural (NLU) del
sistema de atencion de Lina's Pet Salon, un negocio de grooming canino en Quito.

Tu unica tarea es analizar el mensaje del cliente y devolver un objeto JSON
con:
1. La intencion del mensaje, que debe ser exactamente una de: "agendar",
   "consultar" o "general".
   - "agendar": el cliente quiere agendar, reagendar o cancelar una cita.
   - "consultar": el cliente pregunta por servicios, precios o disponibilidad
     sin pedir agendar todavia.
   - "general": saludo, agradecimiento, o cualquier otra cosa que no encaje
     en las dos anteriores.
2. Un nivel de confianza entre 0 y 1.
3. Las entidades relevantes que puedas identificar explicitamente en el
   mensaje (servicio mencionado, fecha/hora sugerida, tipo de mascota). Si
   una entidad no aparece en el mensaje, devuelve null para ese campo; no
   inventes informacion que el cliente no dio.

No respondas al cliente. Solo clasifica y extrae."""


@dataclass
class ResultadoNLU:
    intencion: str
    confianza: float
    servicio_mencionado: str | None = None
    fecha_hora_sugerida: str | None = None
    tipo_mascota: str | None = None
    entidades: dict = field(default_factory=dict)


def clasificar_mensaje(mensaje: str, client: genai.Client) -> ResultadoNLU:
    """
    Clasifica la intencion y extrae entidades de un mensaje entrante.

    Criterio de aceptacion SCRUM-60: distingue correctamente entre las 3
    intenciones y registra un log de la clasificacion para trazabilidad.

    Criterio de aceptacion SCRUM-61: reconoce al menos fecha/hora relativa
    y tipo de servicio mencionado explicitamente.
    """
    response = client.models.generate_content(
        model=MODEL,
        contents=mensaje,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=NLU_SCHEMA,
            temperature=0.1,  # clasificacion, no generacion creativa
        ),
    )

    data = json.loads(response.text)
    entidades = data["entidades"]

    resultado = ResultadoNLU(
        intencion=data["intencion"],
        confianza=float(data["confianza"]),
        servicio_mencionado=entidades.get("servicio_mencionado"),
        fecha_hora_sugerida=entidades.get("fecha_hora_sugerida"),
        tipo_mascota=entidades.get("tipo_mascota"),
        entidades=entidades,
    )

    # Log de trazabilidad exigido por el criterio de aceptacion de SCRUM-60.
    # TODO: en produccion, persistir esto en Supabase (tabla nlu_logs) en
    # lugar de solo loguear a stdout, para poder evaluar el modelo despues
    # (SCRUM-64) sin depender de logs efimeros de Railway.
    logger.info(
        "NLU | mensaje=%r | intencion=%s | confianza=%.2f | entidades=%s",
        mensaje,
        resultado.intencion,
        resultado.confianza,
        entidades,
    )

    return resultado


if __name__ == "__main__":
    # Prueba manual rapida. Requiere GEMINI_API_KEY en el entorno.
    client = genai.Client()

    ejemplos = [
        "Hola, quisiera agendar un bano para mi perrito para manana a las 3pm",
        "Cuanto cuesta el servicio de corte para un perro mediano?",
        "Buenas tardes!",
    ]

    for ejemplo in ejemplos:
        r = clasificar_mensaje(ejemplo, client)
        print(r)
