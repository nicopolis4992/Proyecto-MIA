"""
Grabación y reproducción de llamadas a Gemini (solo para desarrollo y pruebas).

Cada llamada (generate_content / embed_content) se identifica por un hash de
lo que se envía (modelo, contenido e instrucciones). La primera vez se llama a
Gemini y la respuesta se guarda en GEMINI_CACHE_DIR; las siguientes se leen
del disco sin gastar créditos. Si cambia un prompt, cambia el hash y esa
llamada se vuelve a grabar.

    GEMINI_CACHE_DIR=tests/grabaciones       activa la caché (lee y graba)
    GEMINI_CACHE_SOLO_LECTURA=1              no llama nunca a Gemini: si falta
                                             una grabación, falla (para pytest)

En producción no se define GEMINI_CACHE_DIR y no hay ningún cambio.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace


class GrabacionFaltante(RuntimeError):
    pass


def _huella(*partes) -> str:
    return hashlib.sha256(repr(partes).encode("utf-8", "surrogatepass")).hexdigest()[:24]


class _ModelosCacheados:
    def __init__(self, modelos, carpeta: Path, solo_lectura: bool):
        self._modelos, self._carpeta, self._solo_lectura = modelos, carpeta, solo_lectura

    def _leer_o_llamar(self, clave: str, llamar, serializar):
        ruta = self._carpeta / f"{clave}.json"
        if ruta.exists():
            return json.loads(ruta.read_text(encoding="utf-8"))
        if self._solo_lectura:
            raise GrabacionFaltante(
                f"No hay grabación {ruta.name}. Cambió un prompt o un escenario: volver a grabar sin "
                "GEMINI_CACHE_SOLO_LECTURA (gasta créditos una vez).")
        datos = serializar(llamar())
        self._carpeta.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        return datos

    def generate_content(self, *, model, contents, config=None):
        clave = _huella("generate", model, contents, config)
        datos = self._leer_o_llamar(
            clave, lambda: self._modelos.generate_content(model=model, contents=contents, config=config),
            lambda r: {"text": r.text})
        return SimpleNamespace(text=datos["text"])

    def embed_content(self, *, model, contents, config=None):
        clave = _huella("embed", model, contents, config)
        datos = self._leer_o_llamar(
            clave, lambda: self._modelos.embed_content(model=model, contents=contents, config=config),
            lambda r: {"embeddings": [list(e.values) for e in r.embeddings]})
        return SimpleNamespace(embeddings=[SimpleNamespace(values=v) for v in datos["embeddings"]])


class ClienteCacheado:
    """Envuelve un genai.Client exponiendo solo `models`, como lo usan los agentes."""

    def __init__(self, cliente, carpeta: str | Path, solo_lectura: bool = False):
        # Se conserva la referencia al cliente: si se libera, genai cierra su
        # conexion HTTP y las llamadas fallan ("client has been closed").
        self._cliente = cliente
        self.models = _ModelosCacheados(cliente.models if cliente else None, Path(carpeta), solo_lectura)


def envolver_si_corresponde(cliente):
    carpeta = os.getenv("GEMINI_CACHE_DIR", "")
    if not carpeta:
        return cliente
    return ClienteCacheado(cliente, carpeta, os.getenv("GEMINI_CACHE_SOLO_LECTURA") == "1")
