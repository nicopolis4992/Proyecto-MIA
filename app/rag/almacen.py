"""
Almacenamiento vectorial (SCRUM-67) con dos implementaciones de la misma
interfaz:

- AlmacenLocal: archivo JSON versionado en el repo (app/rag/indice_local.json).
  Busqueda exacta por producto punto. Para ~50 fragmentos es instantaneo y
  no requiere infraestructura: es el backend por defecto del prototipo.
- AlmacenPgvector: tabla en Supabase (Postgres + pgvector), el backend
  definido en techContext. Se activa con RAG_BACKEND=pgvector y
  SUPABASE_DB_URL. Esquema en app/rag/esquema_pgvector.sql.

Ambos guardan el hash del texto de cada fragmento para que la re-indexacion
(SCRUM-70) solo recalcule embeddings de lo que cambio.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

RUTA_INDICE_LOCAL = Path(__file__).parent / "indice_local.json"


@dataclass
class Resultado:
    id: str
    fuente: str
    titulo: str
    texto: str
    similitud: float


class Almacen(Protocol):
    def hashes(self) -> dict[str, str]: ...
    def upsert(self, registros: list[dict]) -> None: ...
    def eliminar(self, ids: list[str]) -> None: ...
    def buscar(self, vector: list[float], k: int) -> list[Resultado]: ...


class AlmacenLocal:
    def __init__(self, ruta: Path = RUTA_INDICE_LOCAL, modelo: str = "", dimension: int = 0):
        self.ruta = Path(ruta)
        self.datos = {"modelo": modelo, "dimension": dimension, "fragmentos": {}}
        if self.ruta.exists():
            guardado = json.loads(self.ruta.read_text(encoding="utf-8"))
            # Si cambia el modelo o la dimension, los vectores viejos no son
            # comparables con los nuevos: se descarta el indice completo.
            if (not modelo or guardado.get("modelo") == modelo) and (
                not dimension or guardado.get("dimension") == dimension
            ):
                self.datos = guardado

    def hashes(self) -> dict[str, str]:
        return {i: f["hash"] for i, f in self.datos["fragmentos"].items()}

    def upsert(self, registros: list[dict]) -> None:
        for r in registros:
            self.datos["fragmentos"][r["id"]] = r
        self._guardar()

    def eliminar(self, ids: list[str]) -> None:
        for i in ids:
            self.datos["fragmentos"].pop(i, None)
        self._guardar()

    def _guardar(self) -> None:
        self.ruta.write_text(
            json.dumps(self.datos, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    def buscar(self, vector: list[float], k: int) -> list[Resultado]:
        puntuados = [
            Resultado(f["id"], f["fuente"], f["titulo"], f["texto"],
                      sum(a * b for a, b in zip(vector, f["vector"])))
            for f in self.datos["fragmentos"].values()
        ]
        puntuados.sort(key=lambda r: r.similitud, reverse=True)
        return puntuados[:k]


class AlmacenPgvector:
    """
    Requiere `pip install "psycopg[binary]"` y la extension vector habilitada
    en Supabase. NOTA: implementado pero aun no probado contra la instancia
    real de Supabase (no hay credenciales del equipo todavia).
    """

    def __init__(self, dsn: str):
        import psycopg  # import diferido: solo se necesita con este backend

        self.con = psycopg.connect(dsn, autocommit=True)

    @staticmethod
    def _literal(v: list[float]) -> str:
        return "[" + ",".join(f"{x:.7f}" for x in v) + "]"

    def hashes(self) -> dict[str, str]:
        with self.con.cursor() as cur:
            cur.execute("SELECT id, hash FROM rag_fragmentos")
            return dict(cur.fetchall())

    def upsert(self, registros: list[dict]) -> None:
        with self.con.cursor() as cur:
            for r in registros:
                cur.execute(
                    "INSERT INTO rag_fragmentos (id, fuente, titulo, texto, hash, embedding) "
                    "VALUES (%s, %s, %s, %s, %s, %s::vector) "
                    "ON CONFLICT (id) DO UPDATE SET fuente = EXCLUDED.fuente, "
                    "titulo = EXCLUDED.titulo, texto = EXCLUDED.texto, "
                    "hash = EXCLUDED.hash, embedding = EXCLUDED.embedding, "
                    "actualizado = now()",
                    (r["id"], r["fuente"], r["titulo"], r["texto"], r["hash"],
                     self._literal(r["vector"])),
                )

    def eliminar(self, ids: list[str]) -> None:
        if ids:
            with self.con.cursor() as cur:
                cur.execute("DELETE FROM rag_fragmentos WHERE id = ANY(%s)", (ids,))

    def buscar(self, vector: list[float], k: int) -> list[Resultado]:
        with self.con.cursor() as cur:
            cur.execute(
                "SELECT id, fuente, titulo, texto, 1 - (embedding <=> %s::vector) "
                "FROM rag_fragmentos ORDER BY embedding <=> %s::vector LIMIT %s",
                (self._literal(vector), self._literal(vector), k),
            )
            return [Resultado(*fila) for fila in cur.fetchall()]


def crear_almacen(modelo: str = "", dimension: int = 0) -> Almacen:
    if os.getenv("RAG_BACKEND", "local") == "pgvector":
        return AlmacenPgvector(os.environ["SUPABASE_DB_URL"])
    return AlmacenLocal(modelo=modelo, dimension=dimension)
