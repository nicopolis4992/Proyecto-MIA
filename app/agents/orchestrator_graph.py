"""
orchestrator_graph.py

Cubre:
- SCRUM-65: Integrar el agente NLU con el orquestador multiagente

Reemplaza el nodo unico de SCRUM-85 (texto -> Gemini -> respuesta, sin
enrutamiento) por un grafo con enrutamiento condicional real basado en la
intencion que devuelve nlu_extractor.py.

Como los agentes de RAG (SCRUM-66 a 71) y Agenda todavia no existen, este
esqueleto usa nodos "stub" para esos dos casos. Esto permite cumplir el
criterio de aceptacion de SCRUM-65 (enruta correctamente mensajes de prueba
de las 3 intenciones a su nodo correspondiente) sin bloquearse esperando a
que esas historias esten listas. Cuando el Agente RAG este implementado,
solo hay que reemplazar `nodo_rag` por la llamada real.

Requiere: pip install langgraph google-genai
"""

import logging
from typing import Literal, TypedDict

from google import genai
from langgraph.graph import StateGraph, END

# El try/except permite que este archivo funcione de dos formas:
# - Como script suelto (python orchestrator_graph.py desde dentro de agents/)
# - Como parte del paquete app.agents cuando main.py lo importa via app.agent
try:
    from .nlu_extractor import clasificar_mensaje, ResultadoNLU
except ImportError:
    from nlu_extractor import clasificar_mensaje, ResultadoNLU

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orquestador")


class EstadoConversacion(TypedDict):
    mensaje: str
    nlu: ResultadoNLU | None
    respuesta: str | None


# --- Nodo NLU: primer paso del grafo, siempre se ejecuta ---

def nodo_nlu(estado: EstadoConversacion, client: genai.Client) -> EstadoConversacion:
    resultado = clasificar_mensaje(estado["mensaje"], client)
    estado["nlu"] = resultado
    return estado


# --- Funcion de enrutamiento: decide a que nodo ir segun la intencion ---

def enrutar_por_intencion(
    estado: EstadoConversacion,
) -> Literal["agente_rag", "agente_agenda", "agente_general"]:
    intencion = estado["nlu"].intencion

    if intencion == "consultar":
        return "agente_rag"
    if intencion == "agendar":
        return "agente_agenda"
    # "general" y cualquier caso no reconocido caen aqui como fallback seguro
    return "agente_general"


# --- Nodos stub: placeholders hasta que existan los agentes reales ---

def nodo_rag_stub(estado: EstadoConversacion) -> EstadoConversacion:
    # TODO: reemplazar por el Agente RAG real (SCRUM-66 a SCRUM-71) cuando
    # la base vectorial y la recuperacion de contexto esten implementadas.
    servicio = estado["nlu"].servicio_mencionado or "el servicio que preguntas"
    estado["respuesta"] = (
        f"[stub RAG] Consultando informacion del negocio sobre {servicio}..."
    )
    logger.info("Enrutado a agente_rag (stub)")
    return estado


def nodo_agenda_stub(estado: EstadoConversacion) -> EstadoConversacion:
    # TODO: reemplazar por el Agente de Agenda real cuando exista la
    # integracion con Google Calendar y el motor de restricciones.
    fecha = estado["nlu"].fecha_hora_sugerida or "una fecha por confirmar"
    estado["respuesta"] = f"[stub Agenda] Revisando disponibilidad para {fecha}..."
    logger.info("Enrutado a agente_agenda (stub)")
    return estado


def nodo_general(estado: EstadoConversacion, client: genai.Client) -> EstadoConversacion:
    # Este es el unico nodo que reutiliza directamente el comportamiento
    # original de SCRUM-85 (Gemini respondiendo libremente), para saludos,
    # agradecimientos y consultas fuera del alcance de RAG/Agenda.
    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=estado["mensaje"],
    )
    estado["respuesta"] = response.text
    logger.info("Enrutado a agente_general")
    return estado


def construir_grafo(client: genai.Client):
    grafo = StateGraph(EstadoConversacion)

    grafo.add_node("nlu", lambda estado: nodo_nlu(estado, client))
    grafo.add_node("agente_rag", nodo_rag_stub)
    grafo.add_node("agente_agenda", nodo_agenda_stub)
    grafo.add_node("agente_general", lambda estado: nodo_general(estado, client))

    grafo.set_entry_point("nlu")

    # Este es el reemplazo real del "un solo nodo" de SCRUM-85: en lugar de
    # un edge fijo, add_conditional_edges decide el siguiente nodo en
    # tiempo de ejecucion segun la intencion detectada por el NLU.
    grafo.add_conditional_edges(
        "nlu",
        enrutar_por_intencion,
        {
            "agente_rag": "agente_rag",
            "agente_agenda": "agente_agenda",
            "agente_general": "agente_general",
        },
    )

    grafo.add_edge("agente_rag", END)
    grafo.add_edge("agente_agenda", END)
    grafo.add_edge("agente_general", END)

    return grafo.compile()


# --- Instancia compartida para uso en produccion (via app/agent.py) ---
# Se crea una sola vez al importar el modulo, no en cada mensaje, para no
# reconstruir el grafo ni el cliente de Gemini en cada request del webhook.
_client = genai.Client()
_grafo_compilado = construir_grafo(_client)


def get_reply(mensaje: str) -> str:
    """
    Punto de entrada que usa app/agent.py (y por lo tanto main.py) para
    obtener una respuesta. Mantiene la misma firma que la version minima
    de SCRUM-85 (texto entra, texto sale) para no tener que tocar main.py.
    """
    estado_final = _grafo_compilado.invoke(
        {"mensaje": mensaje, "nlu": None, "respuesta": None}
    )
    return estado_final["respuesta"]


if __name__ == "__main__":
    # Prueba manual del criterio de aceptacion de SCRUM-65: enrutar
    # mensajes de prueba de las 3 intenciones a su agente correspondiente.
    client = genai.Client()
    app = construir_grafo(client)

    mensajes_de_prueba = [
        "Quisiera agendar un bano para mi perrito manana a las 3pm",
        "Cuanto cuesta el servicio de corte para un perro mediano?",
        "Buenas tardes, gracias por la atencion!",
    ]

    for mensaje in mensajes_de_prueba:
        resultado = app.invoke({"mensaje": mensaje, "nlu": None, "respuesta": None})
        print(f"\nMensaje: {mensaje}")
        print(f"Intencion detectada: {resultado['nlu'].intencion}")
        print(f"Respuesta: {resultado['respuesta']}")
