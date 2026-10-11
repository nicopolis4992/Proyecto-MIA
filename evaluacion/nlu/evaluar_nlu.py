"""
SCRUM-64 — Evaluación del agente NLU (clasificación de intención + entidades).

Evalúa el NLU que usa el bot (app/agents/nlu_extractor.py, Gemini) sobre el
conjunto de prueba de SCRUM-63 (datasets/nlu/dataset_nlu_test.csv) y lo
compara con la línea base TF-IDF + regresión logística de Daniel Loza
(datasets/nlu/reporte_baseline.json), sobre la MISMA partición.

    python -m evaluacion.nlu.evaluar_nlu                 # set de prueba (56)
    python -m evaluacion.nlu.evaluar_nlu --conjunto entrenamiento  # 222 (ciego para el prompt)
    python -m evaluacion.nlu.evaluar_nlu --conjunto completo   # los 278

Las respuestas de Gemini se graban en evaluacion/nlu/grabaciones/: repetir la
evaluación no gasta créditos mientras no cambie el prompt. Los resultados van
a evaluacion/nlu/resultados/ (JSON + Markdown para el informe).

Métricas:
- Intención: exactitud, F1 macro y ponderado, precisión/recall/F1 por clase,
  matriz de confusión, errores con el texto.
- Confianza: media en aciertos vs. errores (¿la confianza sirve para detectar
  cuándo dudar?).
- Entidades (solo las que el NLU de producción extrae): recall de fecha/hora
  sobre mensajes con `temporalidad` anotada y de tipo de mascota sobre
  mensajes con `raza` o `tamano`; y tasa de falsas fechas en mensajes sin
  temporalidad.

ADVERTENCIA (de SCRUM-63): el corpus es mayoritariamente sintético. Estas
métricas miden el acuerdo con la guía de anotación, no el desempeño en
producción; recalcular con el corpus real anotado.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

DIR = Path(__file__).parent
DATOS = RAIZ / "datasets" / "nlu"
ETIQUETAS = ["agendar_cita", "consultar_servicio_producto", "consulta_general"]
# Intenciones del bot -> etiquetas del dataset (SCRUM-63)
DEL_BOT = {"agendar": "agendar_cita", "consultar": "consultar_servicio_producto", "general": "consulta_general"}


def cargar(conjunto: str) -> list[dict]:
    archivo = {"prueba": "dataset_nlu_test.csv", "entrenamiento": "dataset_nlu_train.csv",
               "completo": "dataset_nlu_completo.csv"}[conjunto]
    return list(csv.DictReader(open(DATOS / archivo, encoding="utf-8")))


def evaluar(conjunto: str, solo_lectura: bool) -> dict:
    os.environ["GEMINI_CACHE_DIR"] = str(DIR / "grabaciones")
    if solo_lectura:
        os.environ["GEMINI_CACHE_SOLO_LECTURA"] = "1"
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

    from app.agents.nlu_extractor import MODEL, PROMPT_VERSION, clasificar_mensaje
    from app.config import crear_cliente_gemini

    cliente = crear_cliente_gemini()
    filas = cargar(conjunto)
    reales, predichas, detalle = [], [], []
    for i, f in enumerate(filas, 1):
        t0 = time.perf_counter()
        r = clasificar_mensaje(f["texto"], cliente)
        ms = (time.perf_counter() - t0) * 1000
        pred = DEL_BOT.get(r.intencion, "consulta_general")
        reales.append(f["intencion"])
        predichas.append(pred)
        detalle.append({"id": f["id"], "texto": f["texto"], "real": f["intencion"], "predicho": pred,
                        "confianza": r.confianza, "entidades_anotadas": json.loads(f["entidades"] or "{}"),
                        "fecha_hora": r.fecha_hora_sugerida, "tipo_mascota": r.tipo_mascota,
                        "servicio": r.servicio_mencionado, "ms": round(ms)})
        print(f"[{i}/{len(filas)}] {'✓' if pred == f['intencion'] else '✗'} {f['texto'][:60]}")

    reporte = classification_report(reales, predichas, labels=ETIQUETAS, output_dict=True, zero_division=0)
    mc = confusion_matrix(reales, predichas, labels=ETIQUETAS).tolist()

    aciertos = [d for d in detalle if d["real"] == d["predicho"]]
    errores = [d for d in detalle if d["real"] != d["predicho"]]

    def _media(xs):
        return round(sum(xs) / len(xs), 3) if xs else None

    con_fecha = [d for d in detalle if "temporalidad" in d["entidades_anotadas"]]
    sin_fecha = [d for d in detalle if "temporalidad" not in d["entidades_anotadas"]]
    con_mascota = [d for d in detalle if {"raza", "tamano"} & set(d["entidades_anotadas"])]

    return {
        "conjunto": conjunto,
        "n": len(detalle),
        "modelo": MODEL,
        "version_prompt": PROMPT_VERSION,
        "intencion": {
            "exactitud": round(accuracy_score(reales, predichas), 4),
            "f1_macro": round(f1_score(reales, predichas, labels=ETIQUETAS, average="macro", zero_division=0), 4),
            "f1_ponderado": round(f1_score(reales, predichas, labels=ETIQUETAS, average="weighted", zero_division=0), 4),
            "por_clase": {e: {k: round(v, 3) for k, v in reporte[e].items()} for e in ETIQUETAS},
            "matriz_confusion": {"etiquetas": ETIQUETAS, "matriz": mc},
        },
        "confianza": {"media_aciertos": _media([d["confianza"] for d in aciertos]),
                      "media_errores": _media([d["confianza"] for d in errores])},
        "entidades": {
            "recall_fecha_hora": _media([1.0 if d["fecha_hora"] else 0.0 for d in con_fecha]),
            "n_con_temporalidad": len(con_fecha),
            "falsas_fechas": _media([1.0 if d["fecha_hora"] else 0.0 for d in sin_fecha]),
            "recall_tipo_mascota": _media([1.0 if d["tipo_mascota"] else 0.0 for d in con_mascota]),
            "n_con_raza_o_tamano": len(con_mascota),
        },
        "latencia_ms_mediana": sorted(d["ms"] for d in detalle)[len(detalle) // 2],
        "errores": [{k: d[k] for k in ("id", "texto", "real", "predicho", "confianza")} for d in errores],
        "advertencia": "Corpus mayoritariamente sintético (SCRUM-63): mide acuerdo con la guía de anotación, "
                       "no desempeño en producción. Recalcular con el corpus real anotado.",
    }


def markdown(res: dict, base: dict | None) -> str:
    i = res["intencion"]
    corto = {"agendar_cita": "agendar", "consultar_servicio_producto": "consultar", "consulta_general": "general"}
    l = [f"# Evaluación NLU — prompt {res['version_prompt']} ({res['modelo']})", "",
         f"Conjunto: **{res['conjunto']}** ({res['n']} mensajes). {res['advertencia']}", "",
         "| Métrica | Gemini (bot) |" + (" Línea base TF-IDF |" if base else ""),
         "|---|---|" + ("---|" if base else ""),
         f"| Exactitud | {i['exactitud']:.3f} |" + (" — |" if base else ""),
         f"| F1 macro | {i['f1_macro']:.3f} |" + (f" {base['f1_macro_test']:.3f} |" if base else ""),
         f"| F1 ponderado | {i['f1_ponderado']:.3f} |" + (f" {base['f1_ponderado_test']:.3f} |" if base else ""),
         "", "**Por clase**", "", "| Intención | Precisión | Recall | F1 | n |", "|---|---|---|---|---|"]
    for e, m in i["por_clase"].items():
        l.append(f"| {corto[e]} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1-score']:.3f} | {int(m['support'])} |")
    l += ["", "**Matriz de confusión** (filas = real, columnas = predicho)", "",
          "| | " + " | ".join(corto[e] for e in ETIQUETAS) + " |", "|---|---|---|---|"]
    for e, fila in zip(ETIQUETAS, i["matriz_confusion"]["matriz"]):
        l.append(f"| **{corto[e]}** | " + " | ".join(str(x) for x in fila) + " |")
    c, en = res["confianza"], res["entidades"]
    l += ["", f"**Confianza media:** aciertos {c['media_aciertos']} · errores {c['media_errores']}",
          f"**Entidades:** recall fecha/hora {en['recall_fecha_hora']} (n={en['n_con_temporalidad']}) · "
          f"falsas fechas {en['falsas_fechas']} · recall tipo de mascota {en['recall_tipo_mascota']} "
          f"(n={en['n_con_raza_o_tamano']})",
          f"**Latencia mediana:** {res['latencia_ms_mediana']} ms (0 si vino de la grabación)", "",
          f"**Errores ({len(res['errores'])})**", "", "| id | Mensaje | Real | Predicho | Conf. |", "|---|---|---|---|---|"]
    for e in res["errores"]:
        l.append(f"| {e['id']} | {e['texto']} | {corto[e['real']]} | {corto[e['predicho']]} | {e['confianza']:.2f} |")
    return "\n".join(l) + "\n"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # "entrenamiento": 222 mensajes nunca inspeccionados al escribir los prompts;
    # el NLU no se entrena, asi que sirven como conjunto ciego.
    ap.add_argument("--conjunto", choices=["prueba", "entrenamiento", "completo"], default="prueba")
    ap.add_argument("--solo-lectura", action="store_true", help="no llamar a Gemini (usar grabaciones)")
    args = ap.parse_args()
    res = evaluar(args.conjunto, args.solo_lectura)
    base = json.loads((DATOS / "reporte_baseline.json").read_text(encoding="utf-8")) if args.conjunto == "prueba" else None
    salida = DIR / "resultados"
    salida.mkdir(exist_ok=True)
    nombre = f"nlu_{res['version_prompt']}_{args.conjunto}"
    (salida / f"{nombre}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    (salida / f"{nombre}.md").write_text(markdown(res, base), encoding="utf-8")
    i = res["intencion"]
    print(f"\nExactitud {i['exactitud']:.3f} · F1 macro {i['f1_macro']:.3f} · errores {len(res['errores'])}"
          f" → {salida / (nombre + '.md')}")


if __name__ == "__main__":
    main()
