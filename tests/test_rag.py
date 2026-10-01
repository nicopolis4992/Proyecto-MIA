"""
Pruebas del Agente RAG (SCRUM-67 a 70) sin red: el embedder falso es una
bolsa de palabras con hashing, suficiente para verificar la logica de
indexado incremental, recuperacion y "no se" sin depender de Gemini.
"""

import hashlib
import math
import re

from conftest import ClienteFalso

from app.rag.agente_rag import RESPUESTA_SIN_CONTEXTO, recuperar, responder
from app.rag.almacen import AlmacenLocal
from app.rag.fragmentador import Fragmento, todos_los_fragmentos
from app.rag.indexador import reindexar


class EmbedderFalso:
    modelo, dimension = "falso", 256

    def __init__(self):
        self.textos_embebidos = []

    def _v(self, texto):
        v = [0.0] * self.dimension
        for palabra in re.findall(r"\w+", texto.lower()):
            v[int(hashlib.md5(palabra.encode()).hexdigest(), 16) % self.dimension] += 1
        n = math.sqrt(sum(x * x for x in v)) or 1
        return [x / n for x in v]

    def embed_documentos(self, textos):
        self.textos_embebidos.extend(textos)
        return [self._v(t) for t in textos]

    def embed_consulta(self, texto):
        return self._v(texto)


def _almacen(tmp_path):
    return AlmacenLocal(tmp_path / "indice.json", modelo="falso", dimension=256)


def test_fragmentos_incluyen_negocio_y_tarifario():
    ids = {f.id for f in todos_los_fragmentos()}
    assert "negocio#cotizacion_con_foto" in ids
    assert "tarifario#servicio_bano" in ids
    assert "tarifario#restriccion_vehicular" in ids


def test_precios_del_rag_salen_del_tarifario():
    """SCRUM-70: un solo origen de verdad para precios."""
    bano = next(f for f in todos_los_fragmentos() if f.id == "tarifario#servicio_bano")
    assert "USD 14.00" in bano.texto and "USD 24.00" in bano.texto


def test_reindexado_incremental(tmp_path):
    almacen, emb = _almacen(tmp_path), EmbedderFalso()
    frags = [Fragmento("a#1", "a.md", "Uno", "baño de perros"),
             Fragmento("a#2", "a.md", "Dos", "corte de uñas")]
    r = reindexar(almacen, emb, frags)
    assert len(r["indexados"]) == 2

    # Sin cambios: no se recalcula nada.
    emb.textos_embebidos.clear()
    r = reindexar(almacen, emb, frags)
    assert r["indexados"] == [] and emb.textos_embebidos == []

    # Cambia un texto y se elimina otro: solo se toca lo necesario.
    frags = [Fragmento("a#1", "a.md", "Uno", "baño de perros con precio nuevo")]
    r = reindexar(almacen, emb, frags)
    assert r["indexados"] == ["a#1"] and r["eliminados"] == ["a#2"]
    assert set(_almacen(tmp_path).hashes()) == {"a#1"}  # persistido en disco


def test_recupera_el_fragmento_correcto(tmp_path):
    almacen, emb = _almacen(tmp_path), EmbedderFalso()
    reindexar(almacen, emb)
    top = recuperar("descuento por mascota adicional segunda mascota", almacen, emb, k=1, umbral=0.0)
    assert top[0].id == "tarifario#multimascota"


def test_sin_contexto_no_llama_al_llm(tmp_path):
    almacen, emb = _almacen(tmp_path), EmbedderFalso()
    reindexar(almacen, emb)
    cliente = ClienteFalso()
    r = responder("xyzzy qwerty", cliente, almacen, emb, umbral=0.5)
    assert not r.fundamentada
    assert r.texto == RESPUESTA_SIN_CONTEXTO
    assert cliente.llamadas == []


def test_con_contexto_pasa_fragmentos_al_llm(tmp_path):
    almacen, emb = _almacen(tmp_path), EmbedderFalso()
    reindexar(almacen, emb)
    cliente = ClienteFalso("El baño para perro grande cuesta USD 24.00.")
    r = responder("precio del servicio baño e higiene básica", cliente, almacen, emb, umbral=0.1)
    assert r.fundamentada and r.fuentes
    assert "CONTEXTO" in cliente.llamadas[0]["contents"]
    assert "USD 24.00" in cliente.llamadas[0]["contents"]
