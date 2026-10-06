"""
Indexacion y re-indexacion de la base de conocimiento.

- SCRUM-67: genera embeddings de todos los fragmentos y los guarda.
- SCRUM-70: re-indexacion incremental. Compara el hash del texto de cada
  fragmento con el guardado: solo se recalculan los nuevos o modificados y
  se eliminan los que ya no existen. Procedimiento completo en
  app/rag/README.md.

Uso:
    python -m app.rag.indexador            # incremental
    python -m app.rag.indexador --forzar   # recalcula todo
    python -m app.rag.indexador --probar "cuanto cuesta el bano"
"""

from __future__ import annotations

import argparse
import logging

from app.rag.almacen import Almacen
from app.rag.embeddings import Embedder
from app.rag.fragmentador import Fragmento, todos_los_fragmentos

logger = logging.getLogger("rag.indexador")


def reindexar(almacen: Almacen, embedder: Embedder,
              fragmentos: list[Fragmento] | None = None, forzar: bool = False) -> dict:
    fragmentos = fragmentos if fragmentos is not None else todos_los_fragmentos()
    actuales = {f.id: f for f in fragmentos}
    guardados = almacen.hashes()

    a_indexar = [
        f for f in fragmentos if forzar or guardados.get(f.id) != f.hash
    ]
    a_eliminar = [i for i in guardados if i not in actuales]

    if a_indexar:
        vectores = embedder.embed_documentos([f.texto for f in a_indexar])
        almacen.upsert([
            {"id": f.id, "fuente": f.fuente, "titulo": f.titulo, "texto": f.texto,
             "hash": f.hash, "vector": v}
            for f, v in zip(a_indexar, vectores)
        ])
    if a_eliminar:
        almacen.eliminar(a_eliminar)

    resumen = {
        "total": len(fragmentos),
        "indexados": [f.id for f in a_indexar],
        "eliminados": a_eliminar,
        "sin_cambios": len(fragmentos) - len(a_indexar),
    }
    logger.info(
        "Re-indexacion: %d fragmentos, %d (re)indexados, %d eliminados",
        resumen["total"], len(a_indexar), len(a_eliminar),
    )
    return resumen


def main() -> None:
    from app.config import crear_cliente_gemini
    from app.rag.almacen import crear_almacen
    from app.rag.embeddings import EmbedderGemini

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--forzar", action="store_true", help="recalcula todos los embeddings")
    parser.add_argument("--probar", metavar="CONSULTA", help="consulta de prueba tras indexar")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    embedder = EmbedderGemini(crear_cliente_gemini())
    almacen = crear_almacen(embedder.modelo, embedder.dimension)
    resumen = reindexar(almacen, embedder, forzar=args.forzar)
    print(f"Fragmentos: {resumen['total']} | (re)indexados: {len(resumen['indexados'])} "
          f"| eliminados: {len(resumen['eliminados'])} | sin cambios: {resumen['sin_cambios']}")
    for i in resumen["indexados"]:
        print(f"  + {i}")
    for i in resumen["eliminados"]:
        print(f"  - {i}")

    if args.probar:
        print(f"\nConsulta: {args.probar}")
        for r in almacen.buscar(embedder.embed_consulta(args.probar), k=3):
            print(f"  {r.similitud:.3f}  {r.id}")


if __name__ == "__main__":
    main()
