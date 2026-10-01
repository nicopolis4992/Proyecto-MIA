"""
Generacion de embeddings con Gemini (SCRUM-67).

Se usa gemini-embedding-001 con dimension reducida (768 por defecto): para
una base de conocimiento de decenas de fragmentos la diferencia de calidad
frente a 3072 es despreciable y el indice ocupa 4 veces menos. Con
dimension reducida el modelo no devuelve vectores normalizados, por eso se
normalizan aqui (la similitud coseno pasa a ser un producto punto).

Se distingue el tipo de tarea (documento vs consulta): el modelo optimiza
el embedding de forma asimetrica para recuperacion.
"""

from __future__ import annotations

import math
from typing import Protocol

from google import genai
from google.genai import types

from app.config import DIMENSION_EMBEDDINGS, MODELO_EMBEDDINGS

LOTE_MAXIMO = 100


class Embedder(Protocol):
    modelo: str
    dimension: int

    def embed_documentos(self, textos: list[str]) -> list[list[float]]: ...
    def embed_consulta(self, texto: str) -> list[float]: ...


def normalizar(v: list[float]) -> list[float]:
    norma = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norma for x in v]


class EmbedderGemini:
    def __init__(self, client: genai.Client, modelo: str = MODELO_EMBEDDINGS,
                 dimension: int = DIMENSION_EMBEDDINGS):
        self.client = client
        self.modelo = modelo
        self.dimension = dimension

    def _embed(self, textos: list[str], tarea: str) -> list[list[float]]:
        vectores: list[list[float]] = []
        for i in range(0, len(textos), LOTE_MAXIMO):
            resp = self.client.models.embed_content(
                model=self.modelo,
                contents=textos[i:i + LOTE_MAXIMO],
                config=types.EmbedContentConfig(
                    task_type=tarea, output_dimensionality=self.dimension
                ),
            )
            vectores.extend(normalizar(list(e.values)) for e in resp.embeddings)
        return vectores

    def embed_documentos(self, textos: list[str]) -> list[list[float]]:
        return self._embed(textos, "RETRIEVAL_DOCUMENT")

    def embed_consulta(self, texto: str) -> list[float]:
        return self._embed([texto], "RETRIEVAL_QUERY")[0]
