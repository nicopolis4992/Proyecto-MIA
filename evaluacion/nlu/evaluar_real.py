"""
NLU sobre mensajes REALES del historial de WhatsApp (observación NC-09 del comité).

La muestra sale de los export seudonimizados de cuatro clientes (2024-2026):
148 mensajes de la clienta frecuente y una muestra aleatoria de 50 de cada uno de
otros tres chats (semilla 42), etiquetados con la guía de anotación de SCRUM-63, sin mirar
las predicciones; los ruidos de sistema y los mensajes que no permiten decidir se
descartan (regla R7). El archivo etiquetado vive fuera del repositorio
(datos_crudos/, LOPDP): aquí solo se guardan métricas agregadas y los id de los
errores, nunca los textos.

Compara el modelo de lenguaje (prompt v2) con la línea base TF-IDF entrenada con
todo el corpus sintético, con:
- exactitud y F1 macro, con intervalo de confianza del 95 % por bootstrap (2 000 remuestreos);
- prueba de McNemar exacta sobre los mensajes en que los dos modelos discrepan.

    python -m evaluacion.nlu.evaluar_real --archivo datos_crudos/nlu_real_etiquetado.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from math import comb
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
DIR = Path(__file__).parent
ETIQUETAS = ["agendar_cita", "consultar_servicio_producto", "consulta_general"]
DEL_BOT = {"agendar": "agendar_cita", "consultar": "consultar_servicio_producto", "general": "consulta_general"}


def f1_macro(reales, pred):
    from sklearn.metrics import f1_score
    return f1_score(reales, pred, labels=ETIQUETAS, average="macro", zero_division=0)


def bootstrap(reales, pred, n=2000, semilla=42):
    rnd = random.Random(semilla)
    idx = range(len(reales))
    accs, f1s = [], []
    for _ in range(n):
        m = [rnd.choice(idx) for _ in idx]
        r, p = [reales[i] for i in m], [pred[i] for i in m]
        accs.append(sum(a == b for a, b in zip(r, p)) / len(r))
        f1s.append(f1_macro(r, p))
    ic = lambda xs: [round(sorted(xs)[int(0.025 * n)], 3), round(sorted(xs)[int(0.975 * n) - 1], 3)]
    return ic(accs), ic(f1s)


def mcnemar_exacta(reales, a, b):
    """b01: acierta A y falla B; b10: falla A y acierta B. p bilateral exacta (binomial)."""
    b01 = sum(1 for r, x, y in zip(reales, a, b) if x == r and y != r)
    b10 = sum(1 for r, x, y in zip(reales, a, b) if x != r and y == r)
    n = b01 + b10
    if n == 0:
        return b01, b10, 1.0
    k = min(b01, b10)
    p = min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)
    return b01, b10, float(f"{p:.2g}")


def resumen(nombre, reales, pred):
    from sklearn.metrics import classification_report, confusion_matrix
    ic_acc, ic_f1 = bootstrap(reales, pred)
    rep = classification_report(reales, pred, labels=ETIQUETAS, output_dict=True, zero_division=0)
    return {"modelo": nombre,
            "exactitud": round(sum(a == b for a, b in zip(reales, pred)) / len(reales), 3), "ic95_exactitud": ic_acc,
            "f1_macro": round(f1_macro(reales, pred), 3), "ic95_f1_macro": ic_f1,
            "f1_por_clase": {e: round(rep[e]["f1-score"], 3) for e in ETIQUETAS},
            "matriz_confusion": confusion_matrix(reales, pred, labels=ETIQUETAS).tolist()}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archivo", type=Path, required=True)
    ap.add_argument("--solo-lectura", action="store_true")
    args = ap.parse_args()
    # Las grabaciones contienen los textos reales: se guardan fuera del repositorio (LOPDP).
    os.environ["GEMINI_CACHE_DIR"] = str(RAIZ / "datos_crudos" / "grabaciones_nlu_real")
    if args.solo_lectura:
        os.environ["GEMINI_CACHE_SOLO_LECTURA"] = "1"

    from app.agents.nlu_extractor import MODEL, PROMPT_VERSION, clasificar_mensaje
    from app.config import crear_cliente_gemini
    from datasets.nlu.baseline_nlu import construir_pipeline

    filas = list(csv.DictReader(open(args.archivo, encoding="utf-8")))
    reales = [f["intencion"] for f in filas]
    textos = [f["texto"] for f in filas]

    sinteticos = list(csv.DictReader(open(RAIZ / "datasets/nlu/dataset_nlu_completo.csv", encoding="utf-8")))
    base = construir_pipeline().fit([s["texto"] for s in sinteticos], [s["intencion"] for s in sinteticos])
    pred_base = list(base.predict(textos))

    cliente = crear_cliente_gemini()
    pred_llm = []
    for i, t in enumerate(textos, 1):
        pred_llm.append(DEL_BOT.get(clasificar_mensaje(t, cliente).intencion, "consulta_general"))
        print(f"[{i}/{len(textos)}]", end="\r")

    por_cliente = {}
    for c in sorted({f.get("cliente", "cliente_1") for f in filas}):
        ix = [i for i, f in enumerate(filas) if f.get("cliente", "cliente_1") == c]
        r = [reales[i] for i in ix]
        por_cliente[c] = {"n": len(ix),
                          "exactitud_llm": round(sum(reales[i] == pred_llm[i] for i in ix) / len(ix), 3),
                          "f1_macro_llm": round(f1_macro(r, [pred_llm[i] for i in ix]), 3),
                          "exactitud_base": round(sum(reales[i] == pred_base[i] for i in ix) / len(ix), 3),
                          "f1_macro_base": round(f1_macro(r, [pred_base[i] for i in ix]), 3)}

    llm, tfidf = resumen(f"{MODEL} (prompt {PROMPT_VERSION})", reales, pred_llm), resumen("TF-IDF + RL", reales, pred_base)
    b01, b10, p = mcnemar_exacta(reales, pred_llm, pred_base)
    salida = {
        "muestra": {"n": len(reales), "por_clase": {e: reales.count(e) for e in ETIQUETAS},
                    "fuente": "export reales de WhatsApp de cuatro clientes (2024-2026), seudonimizados; "
                              "etiquetado con la guía de SCRUM-63 antes de ver las predicciones"},
        "modelo_de_lenguaje": llm, "linea_base": tfidf,
        "mcnemar": {"acierta_llm_falla_base": b01, "falla_llm_acierta_base": b10, "p_exacta": p},
        "por_cliente": por_cliente,
        "errores_llm": [{"id": f["id"], "real": r, "predicho": q} for f, r, q in zip(filas, reales, pred_llm) if r != q],
        "advertencia": "Cuatro clientes, un solo etiquetado sin segundo anotador: la mayoría de los mensajes son de "
                       "cortesía y logística (consulta general) y la clase consultar tiene pocos casos.",
    }
    out = DIR / "resultados"
    (out / "nlu_real.json").write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    md = [f"# NLU con mensajes reales (n = {len(reales)})", "",
          "| Modelo | Exactitud (IC 95 %) | F1 macro (IC 95 %) | F1 agendar / consultar / general |", "|---|---|---|---|"]
    for r in (llm, tfidf):
        md.append(f"| {r['modelo']} | {r['exactitud']} {r['ic95_exactitud']} | {r['f1_macro']} {r['ic95_f1_macro']} | "
                  f"{' / '.join(str(r['f1_por_clase'][e]) for e in ETIQUETAS)} |")
    md += ["", f"McNemar exacta: el modelo de lenguaje acierta y la línea base falla en {b01} mensajes; al revés en "
           f"{b10} (p = {p}).", "",
           "| Cliente | n | Exactitud LLM | F1 LLM | Exactitud base | F1 base |", "|---|---|---|---|---|---|"]
    md += [f"| {c} | {v['n']} | {v['exactitud_llm']} | {v['f1_macro_llm']} | {v['exactitud_base']} | {v['f1_macro_base']} |"
           for c, v in por_cliente.items()]
    md += ["", salida["advertencia"]]
    (out / "nlu_real.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
