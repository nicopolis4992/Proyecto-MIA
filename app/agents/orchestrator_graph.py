"""
orchestrator_graph.py

Cubre:
- SCRUM-65: Integrar el agente NLU con el orquestador multiagente
- Integracion del prototipo (S4): reemplaza los stubs de RAG y Agenda por
  los agentes reales y agrega dos entradas que no pasan por el NLU:
    * mensajes de la propietaria -> procesador de aprobacion (SCRUM-77/78)
    * fotos -> cotizacion por imagen (SCRUM-103/104)

Flujo:
    START --(propietaria)--> aprobacion --> END
          --(imagen)-------> cotizacion_imagen --> END
          --(texto)--------> nlu --consultar--> agente_rag --> END
                                 --agendar----> agente_agenda --> END
                                 --general----> agente_general --> END
                                   (general con una reserva en curso -> agente_agenda)

El estado de la conversacion entre mensajes (reserva a medio llenar, fotos
intentadas, cita en aprobacion) vive en el repositorio, indexado por numero
de WhatsApp; el grafo en si es sin estado.

Requiere: pip install langgraph google-genai
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

# El try/except permite que este archivo funcione de dos formas:
# - Como script suelto (python orchestrator_graph.py desde dentro de agents/)
# - Como parte del paquete app.agents cuando main.py lo importa via app.agent
try:
    from .nlu_extractor import ResultadoNLU, clasificar_mensaje
except ImportError:
    from nlu_extractor import ResultadoNLU, clasificar_mensaje

from google.genai import types

from app.agenda.agente_agenda import AgenteAgenda, reserva_vacia
from app.agenda.aprobacion import ProcesadorAprobacion
from app.agenda.disponibilidad import cargar_config
from app.config import MODELO_LLM, PROPIETARIA_WHATSAPP, RUTA_TARIFARIO, ahora
from app.cotizacion.cotizador_imagen import procesar_foto
from app.cotizacion.cotizador import Cotizador

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orquestador")

MENSAJE_ERROR = ("Disculpe, tuve un inconveniente técnico procesando su mensaje. "
                 "¿Me lo puede repetir en un momento? 🙏")


class EstadoConversacion(TypedDict, total=False):
    remitente: str
    mensaje: str
    imagen: bytes | None
    id_citado: str | None          # id del mensaje al que se responde (cita)
    nlu: ResultadoNLU | None
    en_flujo_agenda: bool
    respuesta: str | None


@dataclass
class Dependencias:
    client: object
    repo: object
    mensajero: object
    cotizador: Cotizador
    agente_rag: object
    agenda: AgenteAgenda
    aprobacion: ProcesadorAprobacion
    clasificador: object
    propietaria: str


# --- Enrutamiento ---

def enrutar_entrada(estado: EstadoConversacion, propietaria: str) -> Literal["aprobacion", "cotizacion_imagen", "nlu"]:
    if propietaria and estado["remitente"] == propietaria:
        return "aprobacion"
    if estado.get("imagen"):
        return "cotizacion_imagen"
    return "nlu"


_INTERROGATIVOS = ("cuanto", "cuánto", "que ", "qué", "como ", "cómo", "donde", "dónde", "cuando",
                   "cuándo", "cual", "cuál", "tienen", "hacen", "puedo", "pueden", "aceptan", "hay ")


def parece_pregunta(texto: str) -> bool:
    t = texto.strip().lower()
    return "?" in t or "¿" in t or t.startswith(_INTERROGATIVOS)


def enrutar_por_intencion(
    estado: EstadoConversacion,
) -> Literal["agente_rag", "agente_agenda", "agente_general"]:
    intencion = estado["nlu"].intencion

    # Con una reserva en curso, describir a la mascota ("su pelo le crece y
    # hay que cortarlo") suena a "consultar" para el NLU, pero es la respuesta
    # a una pregunta del agente de agenda. Solo una pregunta explicita va al RAG.
    if intencion == "consultar" and estado.get("en_flujo_agenda") and not parece_pregunta(estado["mensaje"]):
        return "agente_agenda"
    if intencion == "consultar":
        return "agente_rag"
    if intencion == "agendar":
        return "agente_agenda"
    # Un "general" en medio de una reserva suele ser la respuesta a una
    # pregunta del agente de agenda ("se llama Toby", "el viernes").
    if estado.get("en_flujo_agenda"):
        return "agente_agenda"
    # "general" y cualquier caso no reconocido caen aqui como fallback seguro
    return "agente_general"


# --- Nodos ---

def nodo_nlu(estado: EstadoConversacion, d: Dependencias) -> EstadoConversacion:
    estado["nlu"] = clasificar_mensaje(estado["mensaje"], d.client)
    estado["en_flujo_agenda"] = d.repo.obtener_sesion(estado["remitente"]).get("flujo") == "agendando"
    return estado


def nodo_rag(estado: EstadoConversacion, d: Dependencias) -> EstadoConversacion:
    r = d.agente_rag(estado["mensaje"])
    estado["respuesta"] = r.texto
    if not r.fundamentada and d.propietaria:
        # El cliente recibio "le comento a la propietaria": hay que hacerlo.
        d.mensajero.enviar(d.propietaria, f"❓ Pregunta sin respuesta en la base de conocimiento "
                                          f"de {estado['remitente']}: \"{estado['mensaje']}\"")
    logger.info("Enrutado a agente_rag (fundamentada=%s)", r.fundamentada)
    return estado


def nodo_agenda(estado: EstadoConversacion, d: Dependencias) -> EstadoConversacion:
    estado["respuesta"] = d.agenda.atender(estado["remitente"], estado["mensaje"], ahora())
    logger.info("Enrutado a agente_agenda")
    return estado


PROMPT_GENERAL = """Eres el asistente de WhatsApp de Lina's Pet Salón, peluquería
canina en Quito. Respondes saludos, agradecimientos y mensajes generales con
calidez y brevedad (1-2 líneas, en español de Ecuador, tratando de "usted").
No des precios, horarios ni datos del negocio: si preguntan algo así, invita a
consultarlo o a enviar una foto de su perrito para cotizar. Si el mensaje no
tiene relación con el negocio, redirige amablemente."""


def nodo_general(estado: EstadoConversacion, d: Dependencias) -> EstadoConversacion:
    response = d.client.models.generate_content(
        model=MODELO_LLM, contents=estado["mensaje"],
        config=types.GenerateContentConfig(system_instruction=PROMPT_GENERAL, temperature=0.6),
    )
    estado["respuesta"] = response.text.strip()
    logger.info("Enrutado a agente_general")
    return estado


def nodo_aprobacion(estado: EstadoConversacion, d: Dependencias) -> EstadoConversacion:
    estado["respuesta"] = d.aprobacion.procesar(estado["mensaje"], estado.get("id_citado"), ahora())
    logger.info("Enrutado a aprobacion (propietaria)")
    return estado


def nodo_cotizacion_imagen(estado: EstadoConversacion, d: Dependencias) -> EstadoConversacion:
    tel = estado["remitente"]
    sesion = d.repo.obtener_sesion(tel)
    ya_agendando = sesion.get("flujo") == "agendando"
    reserva = sesion.setdefault("reserva", reserva_vacia())
    mascotas = reserva["mascotas"] or [{}]
    idx = next((i for i, m in enumerate(mascotas) if not m.get("tamano")), 0)
    m = mascotas[idx]

    intento = sesion.get("fotos_intentos", 0) + 1
    # Sin servicio elegido se muestran los dos mas pedidos.
    servicios = [m["servicio"]] if m.get("servicio") else ["basico", "completo"]
    base = {k: v for k, v in m.items() if k != "servicio" and v is not None}
    r = procesar_foto(estado["imagen"], d.clasificador, d.cotizador, intento, servicios, base)

    if r.accion == "pedir_otra_foto":
        sesion["fotos_intentos"] = intento
        d.repo.guardar_sesion(tel, sesion)
        estado["respuesta"] = r.mensaje
        return estado

    for k, v in r.atributos.items():
        if not m.get(k):  # lo declarado por la clienta no se pisa
            m[k] = v
    mascotas[idx] = m
    reserva["mascotas"] = mascotas
    sesion.update(fotos_intentos=0, flujo="agendando", traza_foto=r.traza,
                  revision_manual=sesion.get("revision_manual") or r.revision_manual)
    # Ya se intento con foto: no se vuelve a pedir el tamano por texto.
    sesion.setdefault("preguntado", []).append("tamano")

    if ya_agendando:
        cierre = d.agenda.continuar(tel, sesion, ahora())
    else:
        d.repo.guardar_sesion(tel, sesion)
        cierre = "¿Le gustaría agendar una cita? 🐾"
    estado["respuesta"] = f"{r.mensaje}\n\n{cierre}"
    logger.info("Enrutado a cotizacion_imagen (%s)", r.traza.get("decision"))
    return estado


def construir_grafo(d: Dependencias):
    grafo = StateGraph(EstadoConversacion)

    grafo.add_node("nlu", lambda e: nodo_nlu(e, d))
    grafo.add_node("agente_rag", lambda e: nodo_rag(e, d))
    grafo.add_node("agente_agenda", lambda e: nodo_agenda(e, d))
    grafo.add_node("agente_general", lambda e: nodo_general(e, d))
    grafo.add_node("aprobacion", lambda e: nodo_aprobacion(e, d))
    grafo.add_node("cotizacion_imagen", lambda e: nodo_cotizacion_imagen(e, d))

    grafo.add_conditional_edges(
        START,
        lambda e: enrutar_entrada(e, d.propietaria),
        {"aprobacion": "aprobacion", "cotizacion_imagen": "cotizacion_imagen", "nlu": "nlu"},
    )
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
    for nodo in ("agente_rag", "agente_agenda", "agente_general", "aprobacion", "cotizacion_imagen"):
        grafo.add_edge(nodo, END)

    return grafo.compile()


def crear_dependencias(client=None, repo=None, mensajero=None, propietaria: str | None = None,
                       agente_rag=None, clasificador=None) -> Dependencias:
    from app.config import crear_cliente_gemini
    from app.mensajeria import MensajeroWhatsApp
    from app.persistencia.repositorio import obtener_repositorio
    from app.rag.agente_rag import crear_agente_rag
    from app.vision.clasificador import crear_clasificador

    client = client or crear_cliente_gemini()
    repo = repo or obtener_repositorio()
    mensajero = mensajero or MensajeroWhatsApp(repo)
    propietaria = PROPIETARIA_WHATSAPP if propietaria is None else propietaria
    cotizador = Cotizador(RUTA_TARIFARIO)
    cfg = cargar_config()
    return Dependencias(
        client=client, repo=repo, mensajero=mensajero, cotizador=cotizador,
        agente_rag=agente_rag or crear_agente_rag(client),
        agenda=AgenteAgenda(client, repo, mensajero, cotizador, cfg, propietaria),
        aprobacion=ProcesadorAprobacion(client, repo, mensajero, cotizador, cfg, propietaria),
        clasificador=clasificador or crear_clasificador(client),
        propietaria=propietaria,
    )


# --- Instancia compartida para uso en produccion (via app/agent.py) ---
# Se crea una sola vez, en el primer mensaje (no al importar, para que las
# pruebas y el arranque de FastAPI no dependan de la red), y se reutiliza.
_deps: Dependencias | None = None
_grafo_compilado = None


def configurar(deps: Dependencias) -> None:
    """Permite inyectar dependencias (simulador local, pruebas)."""
    global _deps, _grafo_compilado
    _deps, _grafo_compilado = deps, construir_grafo(deps)


def _grafo():
    if _grafo_compilado is None:
        configurar(crear_dependencias())
    return _grafo_compilado


def procesar_mensaje(remitente: str, texto: str = "", imagen: bytes | None = None,
                     id_citado: str | None = None) -> str | None:
    """
    Punto de entrada del webhook. Devuelve el texto a responder al remitente
    (o None si el agente ya envio lo necesario por su cuenta).
    """
    try:
        estado_final = _grafo().invoke({
            "remitente": remitente, "mensaje": texto, "imagen": imagen,
            "id_citado": id_citado, "nlu": None, "respuesta": None,
        })
        return estado_final.get("respuesta")
    except Exception:  # noqa: BLE001
        logger.exception("Error procesando mensaje de %s", remitente)
        return MENSAJE_ERROR


def get_reply(mensaje: str) -> str:
    """Compatibilidad con la firma de SCRUM-85 (texto entra, texto sale)."""
    return procesar_mensaje("local", mensaje) or ""
