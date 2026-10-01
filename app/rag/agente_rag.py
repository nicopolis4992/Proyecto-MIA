"""
Agente RAG.

- SCRUM-68: recupera los fragmentos mas relevantes para la consulta.
- SCRUM-69: genera la respuesta usando UNICAMENTE el contexto recuperado.
  Si ningun fragmento supera el umbral de similitud, no se llama al LLM:
  se responde que no se tiene esa informacion y que la propietaria le
  ayudara. Asi el "no se" no depende de que el LLM obedezca el prompt.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from google import genai
from google.genai import types

from app.config import MODELO_LLM
from app.rag.almacen import Almacen, Resultado
from app.rag.embeddings import Embedder

logger = logging.getLogger("rag")

K_FRAGMENTOS = int(os.getenv("RAG_K", "4"))
# Calibrado el 30-sep con gemini-embedding-001 @768 sobre 12 consultas:
# las cubiertas por la base dan top-1 entre 0.67 y 0.80; las no cubiertas
# (direccion, tarjeta, comida para gatos, futbol) entre 0.53 y 0.64.
# Recalibrar con el conjunto de evaluacion de SCRUM-71.
UMBRAL_SIMILITUD = float(os.getenv("RAG_UMBRAL", "0.66"))

RESPUESTA_SIN_CONTEXTO = (
    "No tengo esa información a la mano. Le comento a la propietaria para "
    "que le responda directamente lo antes posible."
)

PROMPT_SISTEMA = """Eres el asistente de WhatsApp de Lina's Pet Salón, un negocio
de grooming canino en Quito. Respondes consultas de clientes.

Reglas obligatorias:
1. Responde SOLO con la información del CONTEXTO. No uses conocimiento propio
   sobre precios, horarios, direcciones ni políticas.
2. Si el contexto no contiene la respuesta (total o parcialmente), dilo con
   naturalidad y ofrece que la propietaria le responda. No inventes.
3. Los precios deben copiarse exactamente del contexto. Si el precio depende
   del tamaño o pelaje y no lo sabes, da los valores por tamaño y sugiere
   enviar una foto de la mascota para una cotización exacta.
4. Tono cálido y cercano, en español de Ecuador, tratando de "usted".
   Mensaje breve apto para WhatsApp (máximo ~5 líneas), sin markdown.
   No uses encabezados genéricos como "Estimado cliente"; ve al punto.
5. No deduzcas información que el contexto no dice explícitamente (por
   ejemplo, que algo "no tiene restricciones" o un horario de atención).
"""


@dataclass
class RespuestaRAG:
    texto: str
    fundamentada: bool
    fuentes: list[Resultado] = field(default_factory=list)


def recuperar(consulta: str, almacen: Almacen, embedder: Embedder,
              k: int = K_FRAGMENTOS, umbral: float = UMBRAL_SIMILITUD) -> list[Resultado]:
    resultados = almacen.buscar(embedder.embed_consulta(consulta), k)
    relevantes = [r for r in resultados if r.similitud >= umbral]
    logger.info(
        "RAG | consulta=%r | top=%s | relevantes=%d",
        consulta, [(r.id, round(r.similitud, 3)) for r in resultados], len(relevantes),
    )
    return relevantes


def responder(consulta: str, client: genai.Client, almacen: Almacen, embedder: Embedder,
              k: int = K_FRAGMENTOS, umbral: float = UMBRAL_SIMILITUD) -> RespuestaRAG:
    fragmentos = recuperar(consulta, almacen, embedder, k, umbral)
    if not fragmentos:
        return RespuestaRAG(RESPUESTA_SIN_CONTEXTO, fundamentada=False)

    contexto = "\n\n".join(f"[{i}] {r.texto}" for i, r in enumerate(fragmentos, 1))
    response = client.models.generate_content(
        model=MODELO_LLM,
        contents=f"CONTEXTO:\n{contexto}\n\nPREGUNTA DEL CLIENTE:\n{consulta}",
        config=types.GenerateContentConfig(
            system_instruction=PROMPT_SISTEMA, temperature=0.2
        ),
    )
    return RespuestaRAG(response.text.strip(), fundamentada=True, fuentes=fragmentos)


class AgenteRAG:
    """Envoltura con dependencias ya resueltas, para el orquestador."""

    def __init__(self, client: genai.Client, almacen: Almacen, embedder: Embedder):
        self.client, self.almacen, self.embedder = client, almacen, embedder

    def __call__(self, consulta: str) -> RespuestaRAG:
        return responder(consulta, self.client, self.almacen, self.embedder)


def crear_agente_rag(client: genai.Client) -> AgenteRAG:
    """
    Construye el agente con el backend configurado y sincroniza el indice al
    arrancar: si alguien edito un documento o el tarifario y desplego sin
    re-indexar, aqui se recalculan solo los fragmentos cambiados.
    """
    from app.rag.almacen import crear_almacen
    from app.rag.embeddings import EmbedderGemini
    from app.rag.indexador import reindexar

    embedder = EmbedderGemini(client)
    almacen = crear_almacen(embedder.modelo, embedder.dimension)
    try:
        reindexar(almacen, embedder)
    except Exception as exc:  # noqa: BLE001 - un fallo de red no debe tumbar el arranque
        logger.error("No se pudo sincronizar el indice RAG al arrancar: %s", exc)
    return AgenteRAG(client, almacen, embedder)
