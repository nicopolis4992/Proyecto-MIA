# -*- coding: utf-8 -*-
"""
Proyecto MIA — Lina's Pet Salon
SCRUM-63: Construccion del dataset etiquetado de NLU.

CRITERIOS DE ACEPTACION CUBIERTOS
---------------------------------
  [x] dataset anonimizado          -> anonimizador.py + corpus semilla sin PII
  [x] las 3 categorias representadas
  [x] dividido en train/test        -> particion estratificada, semilla fija

Salidas:
    dataset_nlu_completo.csv
    dataset_nlu_train.csv
    dataset_nlu_test.csv
    dataset_nlu.jsonl          (formato de carga para el agente NLU)
    estadisticas_dataset.json

Uso:
    python build_dataset.py
    python build_dataset.py --corpus-real corpus_anonimizado.csv   # cuando exista
"""

from __future__ import annotations

import argparse
import csv
import json
import unicodedata
from collections import Counter
from pathlib import Path

from sklearn.model_selection import train_test_split

from corpus_semilla import AGENDAR_CITA, CONSULTAR_SERVICIO_PRODUCTO, CONSULTA_GENERAL

AQUI = Path(__file__).parent

SEMILLA = 42
PROPORCION_TEST = 0.20

INTENCIONES = ("agendar_cita", "consultar_servicio_producto", "consulta_general")

CAMPOS = [
    "id", "texto", "intencion", "entidades",
    "origen", "canal", "split", "num_tokens",
]


def normalizar(texto: str) -> str:
    """Clave de comparacion para detectar duplicados: minusculas, sin tildes,
    sin puntuacion ni espacios redundantes. No modifica el texto del dataset."""
    base = unicodedata.normalize("NFKD", texto.lower())
    base = "".join(c for c in base if not unicodedata.combining(c))
    base = "".join(c if c.isalnum() or c.isspace() else " " for c in base)
    return " ".join(base.split())


def cargar_corpus_semilla() -> list[dict]:
    registros: list[dict] = []
    bloques = (
        ("agendar_cita", AGENDAR_CITA),
        ("consultar_servicio_producto", CONSULTAR_SERVICIO_PRODUCTO),
        ("consulta_general", CONSULTA_GENERAL),
    )
    for intencion, bloque in bloques:
        for texto, entidades in bloque:
            registros.append(
                {
                    "texto": texto,
                    "intencion": intencion,
                    "entidades": entidades,
                    "origen": "sintetico",
                    "canal": "whatsapp",
                }
            )
    return registros


def cargar_corpus_real(ruta: Path) -> list[dict]:
    """Incorpora el corpus real ya seudonimizado y anotado, si esta disponible."""
    registros: list[dict] = []
    with open(ruta, encoding="utf-8") as fh:
        for fila in csv.DictReader(fh):
            if fila.get("rol") != "cliente":
                continue
            intencion = (fila.get("intencion") or "").strip()
            if intencion not in INTENCIONES:
                continue  # mensaje aun sin anotar: no entra al dataset
            try:
                entidades = json.loads(fila.get("entidades") or "{}")
            except json.JSONDecodeError:
                entidades = {}
            registros.append(
                {
                    "texto": (fila.get("texto_anonimizado") or "").strip(),
                    "intencion": intencion,
                    "entidades": entidades,
                    "origen": "real",
                    "canal": "whatsapp",
                }
            )
    return registros


def deduplicar(registros: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    """Elimina enunciados equivalentes. Un duplicado repartido entre train y test
    inflaria artificialmente las metricas (fuga de informacion)."""
    vistos: dict[str, str] = {}
    limpios, colisiones = [], []
    for reg in registros:
        clave = normalizar(reg["texto"])
        if clave in vistos:
            colisiones.append((reg["texto"], vistos[clave]))
            continue
        vistos[clave] = reg["texto"]
        limpios.append(reg)
    return limpios, colisiones


def construir(corpus_real: Path | None = None) -> dict:
    registros = cargar_corpus_semilla()
    if corpus_real and corpus_real.exists():
        registros += cargar_corpus_real(corpus_real)

    registros, colisiones = deduplicar(registros)

    for i, reg in enumerate(registros, start=1):
        reg["id"] = f"MIA-{i:04d}"
        reg["num_tokens"] = len(reg["texto"].split())

    textos = [r["texto"] for r in registros]
    etiquetas = [r["intencion"] for r in registros]

    # Particion estratificada: preserva la proporcion de cada intencion en ambos
    # subconjuntos, condicion necesaria con clases desbalanceadas.
    idx_train, idx_test = train_test_split(
        range(len(registros)),
        test_size=PROPORCION_TEST,
        random_state=SEMILLA,
        stratify=etiquetas,
    )
    for i in idx_train:
        registros[i]["split"] = "train"
    for i in idx_test:
        registros[i]["split"] = "test"

    _escribir_csv(AQUI / "dataset_nlu_completo.csv", registros)
    _escribir_csv(AQUI / "dataset_nlu_train.csv", [r for r in registros if r["split"] == "train"])
    _escribir_csv(AQUI / "dataset_nlu_test.csv", [r for r in registros if r["split"] == "test"])
    _escribir_jsonl(AQUI / "dataset_nlu.jsonl", registros)

    stats = _estadisticas(registros, colisiones, textos)
    (AQUI / "estadisticas_dataset.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return stats


def _escribir_csv(ruta: Path, registros: list[dict]) -> None:
    with open(ruta, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CAMPOS)
        writer.writeheader()
        for reg in registros:
            fila = dict(reg)
            fila["entidades"] = json.dumps(reg["entidades"], ensure_ascii=False)
            writer.writerow({k: fila[k] for k in CAMPOS})


def _escribir_jsonl(ruta: Path, registros: list[dict]) -> None:
    with open(ruta, "w", encoding="utf-8") as fh:
        for reg in registros:
            fh.write(json.dumps({k: reg[k] for k in CAMPOS}, ensure_ascii=False) + "\n")


def _estadisticas(registros: list[dict], colisiones, textos) -> dict:
    por_intencion = Counter(r["intencion"] for r in registros)
    por_split = Counter(r["split"] for r in registros)
    cruce = Counter((r["split"], r["intencion"]) for r in registros)
    longitudes = sorted(r["num_tokens"] for r in registros)
    entidades = Counter()
    for r in registros:
        for k in r["entidades"]:
            entidades[k] += 1

    total = len(registros)
    return {
        "total_enunciados": total,
        "duplicados_eliminados": len(colisiones),
        "vocabulario_unico": len({p for t in textos for p in normalizar(t).split()}),
        "distribucion_por_intencion": dict(por_intencion),
        "proporcion_por_intencion": {
            k: round(v / total, 4) for k, v in por_intencion.items()
        },
        "razon_desbalance_max_min": round(
            max(por_intencion.values()) / min(por_intencion.values()), 2
        ),
        "distribucion_por_split": dict(por_split),
        "cruce_split_intencion": {f"{s}|{i}": n for (s, i), n in sorted(cruce.items())},
        "longitud_tokens": {
            "min": longitudes[0],
            "mediana": longitudes[len(longitudes) // 2],
            "media": round(sum(longitudes) / total, 2),
            "p90": longitudes[int(total * 0.9)],
            "max": longitudes[-1],
        },
        "cobertura_entidades": dict(entidades),
        "origen": dict(Counter(r["origen"] for r in registros)),
        "semilla_aleatoria": SEMILLA,
        "proporcion_test": PROPORCION_TEST,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Construye el dataset de NLU (SCRUM-63).")
    parser.add_argument(
        "--corpus-real",
        default=None,
        help="CSV anotado producido por anonimizador.py, si ya esta disponible",
    )
    args = parser.parse_args()

    ruta_real = Path(args.corpus_real) if args.corpus_real else None
    stats = construir(ruta_real)

    print("Dataset construido")
    print("=" * 52)
    print(f"Total de enunciados      : {stats['total_enunciados']}")
    print(f"Duplicados eliminados    : {stats['duplicados_eliminados']}")
    print(f"Vocabulario unico        : {stats['vocabulario_unico']} tipos")
    print(f"Desbalance max/min       : {stats['razon_desbalance_max_min']}:1")
    print()
    print("Distribucion por intencion:")
    for k, v in stats["distribucion_por_intencion"].items():
        pct = stats["proporcion_por_intencion"][k] * 100
        print(f"  {k:<30} {v:>4}  ({pct:5.1f}%)")
    print()
    print("Particion train/test:")
    for k, v in sorted(stats["cruce_split_intencion"].items()):
        print(f"  {k:<45} {v:>4}")
    print()
    print(f"Longitud (tokens): mediana={stats['longitud_tokens']['mediana']} "
          f"media={stats['longitud_tokens']['media']} max={stats['longitud_tokens']['max']}")
    print(f"Cobertura de entidades: {stats['cobertura_entidades']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
