"""
Orquestador multiagente (SCRUM-85).

Version minima para esta semana: un solo nodo que recibe el texto del
cliente y le pide a Gemini una respuesta directa, sin clasificacion de
intencion real todavia (eso es SCRUM-60, en el proximo sprint), sin RAG
y sin agente de agenda. El objetivo de esta version es validar el ciclo
completo de punta a punta: WhatsApp -> webhook -> orquestador -> Gemini
-> respuesta -> WhatsApp.
"""

import os
from typing import TypedDict

from google import genai
from langgraph.graph import END, StateGraph

_MODEL_NAME = "gemini-3.5-flash-lite"
_client = None


def _get_client() -> genai.Client:
    """
    Crea el cliente de Gemini la primera vez que se necesita, no al
    importar el módulo. Esto evita que el servidor falle al arrancar
    (o que los tests fallen al importar) si GEMINI_API_KEY todavía no
    está configurada.
    """
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))
    return _client

_SYSTEM_PROMPT = (
    "Eres el asistente de WhatsApp de Lina's Pet Salon, un negocio de "
    "grooming canino en Quito. Responde de forma breve, amable y en "
    "espanol al siguiente mensaje del cliente. Todavia no tienes acceso "
    "a la agenda real ni al tarifario, asi que si te preguntan por "
    "precios o disponibilidad, responde que un miembro del equipo "
    "confirmara esos detalles pronto."
)


class ConversationState(TypedDict):
    incoming_text: str
    reply_text: str


def _generate_reply(state: ConversationState) -> ConversationState:
    prompt = f"{_SYSTEM_PROMPT}\n\nMensaje del cliente: {state['incoming_text']}"
    response = _get_client().models.generate_content(model=_MODEL_NAME, contents=prompt)
    return {
        "incoming_text": state["incoming_text"],
        "reply_text": (response.text or "").strip(),
    }


_graph_builder = StateGraph(ConversationState)
_graph_builder.add_node("generate_reply", _generate_reply)
_graph_builder.set_entry_point("generate_reply")
_graph_builder.add_edge("generate_reply", END)
graph = _graph_builder.compile()


def get_reply(incoming_text: str) -> str:
    """Punto de entrada que usa main.py para obtener la respuesta del orquestador."""
    result = graph.invoke({"incoming_text": incoming_text, "reply_text": ""})
    return result["reply_text"]
