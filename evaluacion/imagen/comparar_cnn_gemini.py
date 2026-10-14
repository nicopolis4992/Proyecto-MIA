"""
SCRUM-105 — Clasificador de imagen: CNN (EfficientNet-B0) frente a la línea base
de Gemini sin entrenamiento, sobre LAS MISMAS fotos de prueba.

La CNN se evalúa con el CSV de predicciones que deja el entrenamiento en Colab.
Gemini se evalúa con el mismo clasificador que usa el bot (app/vision/clasificador.py).
Las respuestas de Gemini se graban en evaluacion/imagen/grabaciones: repetir es gratis.

    python -m evaluacion.imagen.comparar_cnn_gemini \
        --predicciones-cnn READ/modelo/clasificador_v1_predicciones_test.csv \
        --imagenes READ/para_colab/dataset
    (--solo-lectura para no llamar a Gemini)

Advertencia metodológica: las etiquetas reales se partieron de propuestas de
Gemini que el equipo revisó una por una. Si la revisión dejó una propuesta tal
cual, Gemini "acierta" por construcción: su resultado es una cota optimista.

Con --estandar-oro (etiquetas de la propietaria hechas a ciegas, ver
revisar.py --ciego) la referencia pasa a ser ella: esa es la comparación válida.
También se reporta cuánto coinciden las etiquetas del equipo con las suyas.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
DIR = Path(__file__).parent
CABEZAS = {"tamano": ["pequeno", "mediano", "grande"],
           "grupo": ["A_maquina", "B_deslanado", "C_cepillado", "D_corto"],
           "estado": ["sin_motas", "moderado", "severo"]}


def metricas(reales: list[str], predichas: list[str], clases: list[str], semilla: int = 42) -> dict:
    import numpy as np
    from sklearn.metrics import classification_report, confusion_matrix, f1_score

    pares = [(r, p) for r, p in zip(reales, predichas) if r]
    if not pares:
        return {"n": 0}
    r, p = zip(*pares)
    rep = classification_report(r, p, labels=clases, output_dict=True, zero_division=0)
    rng = np.random.default_rng(semilla)
    r_a, p_a = np.array(r), np.array(p)
    boot = []
    for _ in range(1000):
        i = rng.integers(0, len(r_a), len(r_a))
        boot.append(f1_score(r_a[i], p_a[i], labels=clases, average="macro", zero_division=0))
    return {
        "n": len(r),
        "f1_macro": round(rep["macro avg"]["f1-score"], 3),
        "f1_macro_ic95": [round(float(np.percentile(boot, 2.5)), 3), round(float(np.percentile(boot, 97.5)), 3)],
        "exactitud": round(sum(a == b for a, b in pares) / len(pares), 3),
        "f1_por_clase": {c: round(rep[c]["f1-score"], 3) for c in clases},
        "matriz": confusion_matrix(r, p, labels=clases).tolist(),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predicciones-cnn", type=Path, required=True)
    ap.add_argument("--imagenes", type=Path, required=True, help="carpeta que contiene imagenes/")
    ap.add_argument("--solo-lectura", action="store_true")
    ap.add_argument("--estandar-oro", type=Path, help="CSV del etiquetado ciego de la propietaria")
    args = ap.parse_args()

    os.environ["GEMINI_CACHE_DIR"] = str(DIR / "grabaciones")
    if args.solo_lectura:
        os.environ["GEMINI_CACHE_SOLO_LECTURA"] = "1"
    from app.config import crear_cliente_gemini
    from app.vision.clasificador import ClasificadorGemini

    gemini = ClasificadorGemini(crear_cliente_gemini())
    filas = list(csv.DictReader(open(args.predicciones_cnn, encoding="utf-8")))
    detalle = []
    for i, f in enumerate(filas, 1):
        c = gemini.clasificar((args.imagenes / f["ruta"]).read_bytes())
        detalle.append({**f, "tamano_gemini": c.tamano, "grupo_gemini": c.grupo, "estado_gemini": c.estado,
                        "es_perro_gemini": c.es_perro})
        print(f"[{i}/{len(filas)}] {f['ruta']}: grupo real={f['grupo_real']} cnn={f['grupo_pred']} gemini={c.grupo}")

    referencia = "equipo"
    if args.estandar_oro:
        oro = {Path(f["ruta"]).stem: f for f in csv.DictReader(open(args.estandar_oro, encoding="utf-8-sig"))
               if f.get("revisado") == "si" and f.get("es_perro", "si") == "si"}
        detalle = [{**d, **{f"{c}_equipo": d[f"{c}_real"] for c in CABEZAS},
                    **{f"{c}_real": oro[Path(d["ruta"]).stem][c] for c in CABEZAS}}
                   for d in detalle if Path(d["ruta"]).stem in oro]
        referencia = "propietaria (a ciegas)"

    resultado = {"n_fotos": len(detalle), "referencia": referencia, "cnn": {}, "gemini": {},
                 "advertencia": ("Referencia independiente: etiquetas de la propietaria hechas sin ver propuestas."
                                 if args.estandar_oro else
                                 "Las etiquetas partieron de propuestas de Gemini revisadas por el equipo: "
                                 "el resultado de Gemini es una cota optimista.")}
    if args.estandar_oro:
        resultado["equipo_vs_propietaria"] = {}
    for cab, clases in CABEZAS.items():
        reales = [d[f"{cab}_real"] for d in detalle]
        resultado["cnn"][cab] = metricas(reales, [d[f"{cab}_pred"] for d in detalle], clases)
        resultado["gemini"][cab] = metricas(reales, [d[f"{cab}_gemini"] for d in detalle], clases)
        if args.estandar_oro:
            resultado["equipo_vs_propietaria"][cab] = metricas(reales, [d[f"{cab}_equipo"] for d in detalle], clases)

    salida = DIR / "resultados"
    salida.mkdir(exist_ok=True)
    sufijo = "_estandar_oro" if args.estandar_oro else ""
    (salida / f"cnn_vs_gemini{sufijo}.json").write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(salida / f"cnn_vs_gemini{sufijo}_detalle.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(detalle[0]))
        w.writeheader()
        w.writerows(detalle)

    print(f"\nReferencia: {referencia}")
    print("| Cabeza | CNN F1 macro (IC 95 %) | Gemini F1 macro (IC 95 %) | n |")
    print("|---|---|---|---|")
    for cab in CABEZAS:
        a, b = resultado["cnn"][cab], resultado["gemini"][cab]
        print(f"| {cab} | {a['f1_macro']} {a['f1_macro_ic95']} | {b['f1_macro']} {b['f1_macro_ic95']} | {a['n']} |")
    if args.estandar_oro:
        print("Coincidencia equipo-propietaria (exactitud):",
              {c: resultado["equipo_vs_propietaria"][c].get("exactitud") for c in CABEZAS})
    for cab in CABEZAS:
        print(f"\n{cab}: F1 por clase  CNN {resultado['cnn'][cab]['f1_por_clase']}")
        print(f"{' ' * len(cab)}                Gemini {resultado['gemini'][cab]['f1_por_clase']}")


if __name__ == "__main__":
    main()
