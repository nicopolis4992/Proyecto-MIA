# -*- coding: utf-8 -*-
"""
Proyecto MIA — Lina's Pet Salon
SCRUM-63: Linea base de verificacion del dataset de NLU.

PROPOSITO
---------
Este script NO es el clasificador de produccion. El agente NLU de la Alternativa 1
se construye sobre un LLM orquestado con LangGraph (SCRUM-53). Lo que se hace aqui
es una linea base clasica (TF-IDF + Regresion Logistica) con tres funciones de
control de calidad sobre el dataset:

  1. Separabilidad: si un modelo lineal simple no distingue las tres intenciones,
     el problema no esta en el modelo sino en el esquema de etiquetado.
  2. Fuga de informacion: mide la similitud maxima entre cada enunciado de prueba
     y el conjunto de entrenamiento. Similitudes cercanas a 1.0 indican
     casi-duplicados repartidos entre particiones, que inflan las metricas.
  3. Piso de comparacion: toda mejora que aporte el LLM debe medirse contra este
     valor, no contra cero. Sin piso no hay forma de justificar el costo del LLM.

ADVERTENCIA METODOLOGICA
------------------------
Mientras el corpus sea mayoritariamente sintetico, las metricas de este script
miden la consistencia interna del etiquetado, NO el desempeno esperado en
produccion. Un F1 alto sobre datos sinteticos es esperable y no constituye
evidencia de calidad del sistema. El F1 reportable en el informe de titulacion es
el que se obtenga sobre el corpus real anotado.

Uso:
    python baseline_nlu.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline, FeatureUnion

AQUI = Path(__file__).parent
SEMILLA = 42
UMBRAL_FUGA = 0.90  # similitud coseno por encima de la cual se declara casi-duplicado

INTENCIONES = ["agendar_cita", "consultar_servicio_producto", "consulta_general"]


def cargar(nombre: str) -> tuple[list[str], list[str], list[str]]:
    textos, etiquetas, ids = [], [], []
    with open(AQUI / nombre, encoding="utf-8") as fh:
        for fila in csv.DictReader(fh):
            textos.append(fila["texto"])
            etiquetas.append(fila["intencion"])
            ids.append(fila["id"])
    return textos, etiquetas, ids


def construir_pipeline() -> Pipeline:
    # Union de n-gramas de palabra y de caracter. Los de caracter absorben la
    # variacion ortografica propia del canal (ausencia de tildes, "q" por "que",
    # "xfa", errores de tipeo) sin necesidad de normalizacion previa agresiva.
    return Pipeline(
        [
            (
                "features",
                FeatureUnion(
                    [
                        ("palabra", TfidfVectorizer(
                            analyzer="word", ngram_range=(1, 2),
                            sublinear_tf=True, min_df=1, strip_accents="unicode",
                            lowercase=True,
                        )),
                        ("caracter", TfidfVectorizer(
                            analyzer="char_wb", ngram_range=(3, 5),
                            sublinear_tf=True, min_df=2, strip_accents="unicode",
                            lowercase=True,
                        )),
                    ]
                ),
            ),
            (
                "clf",
                LogisticRegression(
                    max_iter=2000,
                    C=5.0,
                    class_weight="balanced",  # compensa el desbalance entre intenciones
                    random_state=SEMILLA,
                ),
            ),
        ]
    )


def analisis_fuga(x_train: list[str], x_test: list[str], id_test: list[str]) -> dict:
    """Similitud coseno maxima de cada enunciado de prueba contra entrenamiento."""
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), strip_accents="unicode")
    m_train = vec.fit_transform(x_train)
    m_test = vec.transform(x_test)
    sim = (m_test @ m_train.T).toarray()
    max_sim = sim.max(axis=1)
    sospechosos = [
        {
            "id": id_test[i],
            "texto": x_test[i],
            "similitud_max": round(float(max_sim[i]), 4),
            "mas_parecido_en_train": x_train[int(sim[i].argmax())],
        }
        for i in np.where(max_sim >= UMBRAL_FUGA)[0]
    ]
    return {
        "umbral": UMBRAL_FUGA,
        "similitud_media": round(float(max_sim.mean()), 4),
        "similitud_p95": round(float(np.percentile(max_sim, 95)), 4),
        "similitud_maxima": round(float(max_sim.max()), 4),
        "n_sospechosos": len(sospechosos),
        "sospechosos": sospechosos[:10],
    }


def main() -> int:
    x_train, y_train, _ = cargar("dataset_nlu_train.csv")
    x_test, y_test, id_test = cargar("dataset_nlu_test.csv")

    print("Linea base de verificacion del dataset NLU — SCRUM-63")
    print("=" * 62)
    print(f"Entrenamiento: {len(x_train)} enunciados | Prueba: {len(x_test)} enunciados\n")

    # --- Control 1: clasificador trivial -----------------------------------
    trivial = DummyClassifier(strategy="most_frequent", random_state=SEMILLA)
    trivial.fit(x_train, y_train)
    f1_trivial = f1_score(y_test, trivial.predict(x_test), average="macro", zero_division=0)
    print(f"Clasificador trivial (clase mayoritaria)  F1-macro = {f1_trivial:.3f}")

    # --- Control 2: validacion cruzada en entrenamiento ---------------------
    pipe = construir_pipeline()
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEMILLA)
    scores = cross_val_score(pipe, x_train, y_train, cv=cv, scoring="f1_macro")
    print(f"Validacion cruzada 5-fold (train)         F1-macro = "
          f"{scores.mean():.3f} (+/- {scores.std():.3f})")

    # --- Evaluacion en el conjunto de prueba --------------------------------
    pipe.fit(x_train, y_train)
    y_pred = pipe.predict(x_test)
    f1_macro = f1_score(y_test, y_pred, average="macro", zero_division=0)
    f1_pond = f1_score(y_test, y_pred, average="weighted", zero_division=0)
    print(f"Conjunto de prueba retenido               F1-macro = {f1_macro:.3f}")
    print(f"                                          F1-ponderado = {f1_pond:.3f}")
    print(f"Ganancia sobre el clasificador trivial    +{f1_macro - f1_trivial:.3f}\n")

    print("Reporte por intencion (conjunto de prueba)")
    print("-" * 62)
    reporte_txt = classification_report(
        y_test, y_pred, labels=INTENCIONES, digits=3, zero_division=0
    )
    print(reporte_txt)

    print("Matriz de confusion (filas = real, columnas = predicho)")
    print("-" * 62)
    mc = confusion_matrix(y_test, y_pred, labels=INTENCIONES)
    encabezado = " " * 32 + "".join(f"{i[:12]:>14}" for i in INTENCIONES)
    print(encabezado)
    for nombre, fila in zip(INTENCIONES, mc):
        print(f"{nombre:<32}" + "".join(f"{v:>14}" for v in fila))
    print()

    # --- Errores concretos, para realimentar la guia de anotacion -----------
    errores = [
        {"id": id_test[i], "texto": x_test[i], "real": y_test[i], "predicho": y_pred[i]}
        for i in range(len(y_test))
        if y_test[i] != y_pred[i]
    ]
    print(f"Errores de clasificacion: {len(errores)} de {len(y_test)}")
    for e in errores:
        print(f"  [{e['id']}] \"{e['texto'][:58]}\"")
        print(f"       real={e['real']}  ->  predicho={e['predicho']}")
    print()

    # --- Control 3: fuga entre particiones ----------------------------------
    fuga = analisis_fuga(x_train, x_test, id_test)
    print("Control de fuga de informacion entre particiones")
    print("-" * 62)
    print(f"Similitud coseno con el vecino mas cercano en train:")
    print(f"  media = {fuga['similitud_media']:.3f} | "
          f"p95 = {fuga['similitud_p95']:.3f} | max = {fuga['similitud_maxima']:.3f}")
    print(f"  Enunciados sobre el umbral {UMBRAL_FUGA}: {fuga['n_sospechosos']}")
    if fuga["n_sospechosos"]:
        print("  Revisar y reescribir o reasignar los siguientes casos:")
        for s in fuga["sospechosos"]:
            print(f"    [{s['id']}] sim={s['similitud_max']} :: \"{s['texto'][:48]}\"")
    else:
        print("  Sin casi-duplicados: la particion es valida.")
    print()

    resultados = {
        "n_train": len(x_train),
        "n_test": len(x_test),
        "f1_macro_trivial": round(float(f1_trivial), 4),
        "f1_macro_cv_media": round(float(scores.mean()), 4),
        "f1_macro_cv_desviacion": round(float(scores.std()), 4),
        "f1_macro_test": round(float(f1_macro), 4),
        "f1_ponderado_test": round(float(f1_pond), 4),
        "matriz_confusion": {
            "etiquetas": INTENCIONES,
            "matriz": mc.tolist(),
        },
        "errores": errores,
        "control_fuga": fuga,
        "advertencia": (
            "Metricas obtenidas sobre corpus mayoritariamente sintetico. Miden "
            "consistencia del etiquetado, no desempeno en produccion. Recalcular "
            "sobre el corpus real anotado antes de reportar en el informe."
        ),
    }
    (AQUI / "reporte_baseline.json").write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Reporte guardado en reporte_baseline.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
