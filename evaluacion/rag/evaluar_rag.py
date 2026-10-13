"""
SCRUM-71 — Evaluación del agente RAG con un conjunto de preguntas anotado.

El conjunto lo escribe el equipo (Daniel Loza), SIN mirar los documentos de la
base, en un CSV con las columnas de `preguntas_plantilla.csv`:

    pregunta              como la escribiría un cliente
    respuesta_esperada    datos clave que DEBEN aparecer, separados por ";"
                          (ej. "11:00;18:00"). Vacío si debe declinar.
    debe_declinar         si / no: la base NO tiene esa información
    categoria             categoría del fragmento que debería recuperarse
                          (negocio, servicios, tarifario, cotizacion, agenda,
                          horarios, puerta_a_puerta, politicas, faq). Si vale
                          mas de una, separarlas con "|" (ej. "politicas|faq")

Métricas:
- Recuperación: el fragmento de la categoría esperada sale primero (hit@1) o
  entre los k primeros (hit@k).
- Umbral de similitud: para cada umbral, qué tan bien separa "sabe" de "no sabe"
  usando solo la similitud del mejor fragmento. Propone el umbral con mejor
  exactitud balanceada (sirve para recalibrar RAG_UMBRAL, hoy 0,66).
- Respuestas (con --respuestas):
  - exactitud: respondió y aparecen todos los datos esperados;
  - "no sé" correcto: declinó cuando debía;
  - alucinación: respondió con datos cuando debía declinar.

Las llamadas a Gemini se graban en evaluacion/rag/grabaciones: repetir la
evaluación no gasta créditos.

    python -m evaluacion.rag.evaluar_rag --preguntas evaluacion/rag/preguntas.csv             # solo recuperación (barato)
    python -m evaluacion.rag.evaluar_rag --preguntas evaluacion/rag/preguntas.csv --respuestas
    python -m evaluacion.rag.evaluar_rag --preguntas ... --respuestas --solo-lectura          # sin llamar a Gemini
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
DIR = Path(__file__).parent
K = 4


def normalizar(t: str) -> str:
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def contiene_dato(respuesta: str, dato: str) -> bool:
    """Un número cuenta aunque venga con decimales o símbolo ("20" ~ "20.00$", "USD 20")."""
    r, d = normalizar(respuesta), normalizar(dato).strip()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", d):
        buscado = float(d.replace(",", "."))
        return any(float(x.replace(",", ".")) == buscado for x in re.findall(r"\d+(?:[.,]\d+)?", r))
    return d in r


def cargar(ruta: Path) -> list[dict]:
    filas = list(csv.DictReader(open(ruta, encoding="utf-8-sig")))
    for f in filas:
        f["debe_declinar"] = normalizar(f.get("debe_declinar", "")).strip() in ("si", "s", "1", "x")
        f["datos"] = [d.strip() for d in (f.get("respuesta_esperada") or "").split(";") if d.strip()]
    return [f for f in filas if f.get("pregunta", "").strip()]


def evaluar(filas: list[dict], recuperar, responder=None, umbral_actual: float = 0.66) -> dict:
    """
    recuperar(pregunta) -> [(categoria, similitud), ...] ordenado de mayor a menor.
    responder(pregunta) -> (texto, fundamentada). Opcional.
    """
    detalle = []
    for f in filas:
        top = recuperar(f["pregunta"])
        d = {"pregunta": f["pregunta"], "debe_declinar": f["debe_declinar"], "categoria": f.get("categoria", ""),
             "top1_similitud": round(top[0][1], 4) if top else 0.0,
             "categorias_recuperadas": [c for c, _ in top]}
        if not f["debe_declinar"] and d["categoria"]:
            validas = {c.strip() for c in d["categoria"].split("|")}  # "politicas|faq": cualquiera vale
            d["hit1"] = bool(top) and top[0][0] in validas
            d["hitk"] = bool(validas & set(d["categorias_recuperadas"]))
        if responder:
            texto, fundamentada = responder(f["pregunta"])
            d.update(respuesta=texto, respondio=fundamentada)
            if f["debe_declinar"]:
                d["correcta"] = not fundamentada
                d["alucinacion"] = fundamentada
            else:
                faltan = [x for x in f["datos"] if not contiene_dato(texto, x)]
                d["faltan"] = faltan
                d["correcta"] = fundamentada and not faltan
        detalle.append(d)

    sabe = [d for d in detalle if not d["debe_declinar"]]
    no_sabe = [d for d in detalle if d["debe_declinar"]]
    pct = lambda xs: round(100 * sum(xs) / len(xs), 1) if xs else None

    def separar(u):
        tpr = pct([d["top1_similitud"] >= u for d in sabe])        # responde lo que sabe
        tnr = pct([d["top1_similitud"] < u for d in no_sabe])      # declina lo que no sabe
        bal = round((tpr + tnr) / 2, 1) if tpr is not None and tnr is not None else None
        return {"umbral": round(u, 2), "responde_lo_que_sabe_pct": tpr, "declina_lo_que_no_sabe_pct": tnr,
                "exactitud_balanceada_pct": bal}

    curva = [separar(u / 100) for u in range(50, 86)]
    validos = [c for c in curva if c["exactitud_balanceada_pct"] is not None]
    mejor = max(validos, key=lambda c: (c["exactitud_balanceada_pct"], -abs(c["umbral"] - umbral_actual))) if validos else None

    resultado = {
        "n": len(detalle), "n_sabe": len(sabe), "n_no_sabe": len(no_sabe),
        "recuperacion": {"hit1_pct": pct([d["hit1"] for d in sabe if "hit1" in d]),
                         f"hit{K}_pct": pct([d["hitk"] for d in sabe if "hitk" in d])},
        "umbral_actual": separar(umbral_actual),
        "umbral_propuesto": mejor,
        "curva_umbral": curva,
    }
    if responder:
        resultado["respuestas"] = {
            "exactitud_pct": pct([d["correcta"] for d in sabe]),
            "respondio_lo_que_sabe_pct": pct([d["respondio"] for d in sabe]),
            "no_se_correcto_pct": pct([d["correcta"] for d in no_sabe]),
            "alucinacion_pct": pct([d["alucinacion"] for d in no_sabe]),
        }
    resultado["detalle"] = detalle
    return resultado


def markdown(r: dict) -> str:
    l = [f"# Evaluación del RAG (SCRUM-71)\n\n{r['n']} preguntas: {r['n_sabe']} que la base sabe, "
         f"{r['n_no_sabe']} que debe declinar.\n",
         "| Métrica | Valor |", "|---|---|",
         f"| Recuperación: categoría correcta en 1.er lugar | {r['recuperacion']['hit1_pct']} % |",
         f"| Recuperación: categoría correcta entre los {K} primeros | {r['recuperacion'][f'hit{K}_pct']} % |"]
    if "respuestas" in r:
        x = r["respuestas"]
        l += [f"| Exactitud de las respuestas | {x['exactitud_pct']} % |",
              f"| \"No sé\" correcto | {x['no_se_correcto_pct']} % |",
              f"| Alucinación (respondió cuando debía declinar) | {x['alucinacion_pct']} % |"]
    a, p = r["umbral_actual"], r["umbral_propuesto"]
    l += ["", "## Umbral de similitud", "",
          "| | Umbral | Responde lo que sabe | Declina lo que no sabe | Exactitud balanceada |", "|---|---|---|---|---|",
          f"| Actual | {a['umbral']} | {a['responde_lo_que_sabe_pct']} % | {a['declina_lo_que_no_sabe_pct']} % | {a['exactitud_balanceada_pct']} % |"]
    if p:
        l.append(f"| Propuesto | {p['umbral']} | {p['responde_lo_que_sabe_pct']} % | {p['declina_lo_que_no_sabe_pct']} % | {p['exactitud_balanceada_pct']} % |")
    fallas = [d for d in r["detalle"] if d.get("correcta") is False or d.get("hit1") is False]
    if fallas:
        l += ["", "## Casos a revisar", "", "| Pregunta | Esperado | Problema |", "|---|---|---|"]
        for d in fallas:
            if d["debe_declinar"]:
                prob = "respondió cuando debía declinar"
            elif d.get("correcta") is False:
                prob = "no respondió" if not d.get("respondio") else f"faltan: {', '.join(d.get('faltan', []))}"
            else:
                prob = f"recuperó {d['categorias_recuperadas'][:2]} (esperado {d['categoria']})"
            l.append(f"| {d['pregunta']} | {'declinar' if d['debe_declinar'] else d['categoria']} | {prob} |")
    l += ["", "Umbral propuesto con el mismo conjunto evaluado: confirmarlo con preguntas nuevas antes de fijarlo."]
    return "\n".join(l) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preguntas", type=Path, required=True)
    ap.add_argument("--respuestas", action="store_true", help="tambien genera respuestas con Gemini (mas caro)")
    ap.add_argument("--solo-lectura", action="store_true", help="solo usa lo grabado; no llama a Gemini")
    args = ap.parse_args()

    os.environ["GEMINI_CACHE_DIR"] = str(DIR / "grabaciones")
    if args.solo_lectura:
        os.environ["GEMINI_CACHE_SOLO_LECTURA"] = "1"
    from app.config import crear_cliente_gemini
    from app.rag.agente_rag import UMBRAL_SIMILITUD, responder
    from app.rag.almacen import crear_almacen
    from app.rag.embeddings import EmbedderGemini

    cliente = crear_cliente_gemini()
    embedder = EmbedderGemini(cliente)
    almacen = crear_almacen(embedder.modelo, embedder.dimension)
    fragmentos = almacen.datos["fragmentos"]

    def recuperar(p):
        return [((fragmentos.get(r.id, {}).get("metadatos") or {}).get("categoria", ""), r.similitud)
                for r in almacen.buscar(embedder.embed_consulta(p), K)]

    def resp(p):
        r = responder(p, cliente, almacen, embedder)
        return r.texto, r.fundamentada

    res = evaluar(cargar(args.preguntas), recuperar, resp if args.respuestas else None, UMBRAL_SIMILITUD)
    salida = DIR / "resultados"
    salida.mkdir(exist_ok=True)
    (salida / "rag_eval.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    (salida / "rag_eval.md").write_text(markdown(res), encoding="utf-8")
    print(markdown(res))


if __name__ == "__main__":
    main()
