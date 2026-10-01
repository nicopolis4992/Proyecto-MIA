#!/usr/bin/env python3
"""
SCRUM-101 — Orquestador del pipeline de preparación del dataset de imágenes.

Uso
---
    export MIA_SAL_SEUDONIMO='...la misma sal de SCRUM-63...'

    # Demostración reproducible sin fotografías reales (para la revisión de sprint)
    python preparar_dataset.py --simular

    # Ejecución real, cuando lleguen las fotos de la propietaria
    python preparar_dataset.py \
        --stanford  datos/crudo/stanford_dogs/Images \
        --instagram datos/crudo/propias/instagram \
        --captura   datos/crudo/propias/captura \
        --etiquetas datos/crudo/propias/etiquetas.csv \
        --salida    datos/procesado

`etiquetas.csv` es el archivo que llena la propietaria. Columnas mínimas:
    archivo, mascota (nombre o teléfono), peso_kg, pelaje, escala_presente

El pipeline se detiene ante cualquier fallo de integridad. Es deliberado: un
dataset silenciosamente mal etiquetado produce métricas altas y un sistema que
cotiza mal, que es el peor desenlace posible para esta historia.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from clases import clasificar_peso, verificar_contra_tarifario  # noqa: E402
import anonimizacion  # noqa: E402
from anonimizacion import (  # noqa: E402
    SalNoConfigurada,
    agrupar_duplicados,
    hash_perceptual,
    limpiar_metadatos,
    obtener_sal,
    seudonimo,
)
from dataset import (  # noqa: E402
    FUENTE_CAPTURA,
    FUENTE_INSTAGRAM,
    FUENTE_STANFORD,
    SEMILLA,
    Registro,
    escribir_manifiesto,
    particionar,
)
from mapeo_razas import (  # noqa: E402
    construir_mapeo,
    escribir_csv,
    integridad_tabla,
    validar_cobertura,
)
from reporte import brecha, cobertura, cobertura_del_mapeo, imprimir_reporte  # noqa: E402

EXTENSIONES = {".jpg", ".jpeg", ".png", ".webp"}


# ---------------------------------------------------------------------------
# Ingesta
# ---------------------------------------------------------------------------

def ingerir_stanford(raiz: Path, mapa: dict[str, dict], salida: Path) -> list[Registro]:
    """Recorre las carpetas por raza de Stanford Dogs y aplica el mapeo."""
    carpetas = sorted(p for p in raiz.iterdir() if p.is_dir())
    slugs = [c.name.split("-", 1)[-1].lower() for c in carpetas]

    cobertura_mapeo = validar_cobertura(slugs)
    if cobertura_mapeo["sin_mapeo"]:
        raise SystemExit(
            "Razas presentes en el disco pero ausentes de la tabla de mapeo: "
            + ", ".join(cobertura_mapeo["sin_mapeo"])
            + "\nCorrige src/mapeo_razas.py antes de continuar."
        )

    registros: list[Registro] = []
    for carpeta, slug in zip(carpetas, slugs):
        info = mapa[slug]
        if info["uso"] == "excluida":
            continue
        for i, archivo in enumerate(sorted(p for p in carpeta.iterdir()
                                           if p.suffix.lower() in EXTENSIONES)):
            destino = salida / "stanford" / slug / archivo.name
            limpieza = limpiar_metadatos(archivo, destino)
            registros.append(
                Registro(
                    id_imagen=f"sd_{slug}_{i:04d}",
                    fuente=FUENTE_STANFORD,
                    ruta=str(destino.relative_to(salida)),
                    mascota_id=f"sd_{slug}_{i:04d}",  # cada imagen es un animal distinto
                    raza_slug=slug,
                    tamano="" if info["uso"] == "solo_pelaje" else info["tamano"],
                    pelaje=info["pelaje"],
                    origen_etiqueta="derivada_de_raza",
                    tamano_ambiguo=int(info["tamano_ambiguo"]),
                    phash="",
                    tenia_gps=int(limpieza.tenia_gps),
                    revision_manual=0,
                    observaciones=info["pelaje_observacion"],
                )
            )
    return registros


def _leer_etiquetas(ruta: Path) -> dict[str, dict]:
    with ruta.open(encoding="utf-8") as fh:
        return {f["archivo"].strip(): f for f in csv.DictReader(fh)}


def ingerir_propias(raiz: Path, fuente: str, etiquetas: dict[str, dict],
                    sal: bytes, salida: Path) -> list[Registro]:
    """Ingiere fotografías del negocio: limpia metadatos y seudonimiza."""
    registros: list[Registro] = []
    archivos = sorted(p for p in raiz.rglob("*") if p.suffix.lower() in EXTENSIONES)

    for i, archivo in enumerate(archivos):
        fila = etiquetas.get(archivo.name)
        if fila is None:
            print(f"  [aviso] sin etiqueta, se omite: {archivo.name}")
            continue

        destino = salida / fuente / archivo.name
        limpieza = limpiar_metadatos(archivo, destino)

        peso = fila.get("peso_kg", "").strip()
        tamano = clasificar_peso(float(peso)) if peso else ""

        registros.append(
            Registro(
                id_imagen=f"{fuente}_{i:04d}",
                fuente=fuente,
                ruta=str(destino.relative_to(salida)),
                mascota_id=seudonimo(fila["mascota"], sal),
                raza_slug=fila.get("raza_slug", "").strip().lower(),
                tamano=tamano,
                pelaje=fila.get("pelaje", "").strip().lower(),
                origen_etiqueta="declarada_por_propietaria",
                tamano_ambiguo=0,
                escala_presente=int(fila.get("escala_presente", 0) or 0),
                phash=hash_perceptual(destino),
                tenia_gps=int(limpieza.tenia_gps),
                revision_manual=int(fila.get("revision_manual", 0) or 0),
            )
        )
    return registros


def deduplicar(registros: list[Registro]) -> list[Registro]:
    """Elimina casi-duplicados dentro de las fotos propias (pHash, umbral 5)."""
    con_hash = {r.id_imagen: r.phash for r in registros if r.phash}
    grupos = agrupar_duplicados(con_hash)
    a_descartar: set[str] = set()
    for grupo in grupos:
        a_descartar.update(grupo[1:])  # se conserva el primero de cada grupo
    if a_descartar:
        print(f"  Casi-duplicados descartados: {len(a_descartar)} "
              f"en {len(grupos)} grupos.")
    return [r for r in registros if r.id_imagen not in a_descartar]


# ---------------------------------------------------------------------------
# Modo simulación
# ---------------------------------------------------------------------------

def simular(salida: Path, mapa: dict[str, dict]) -> list[Registro]:
    """
    Genera un manifiesto sintético con la forma exacta del real.

    Sirve para dos cosas: demostrar el pipeline completo en la revisión de
    sprint sin disponer todavía de las fotos, y ejercitar los controles de fuga
    y contaminación. Las imágenes NO se crean: solo el manifiesto, porque lo que
    se quiere ejercitar es la lógica de partición y de cobertura.
    """
    rng = random.Random(SEMILLA)
    registros: list[Registro] = []

    utilizables = [v for v in mapa.values() if v["uso"] == "completa"]
    for i, info in enumerate(utilizables * 2):
        registros.append(
            Registro(
                id_imagen=f"sd_sim_{i:04d}",
                fuente=FUENTE_STANFORD,
                ruta=f"stanford/{info['slug']}/sim_{i:04d}.jpg",
                mascota_id=f"sd_sim_{i:04d}",
                raza_slug=info["slug"],
                tamano=info["tamano"],
                pelaje=info["pelaje"],
                origen_etiqueta="derivada_de_raza",
            )
        )

    # Escenario realista: 14 mascotas del negocio, 3 fotos cada una
    pesos = [2.5, 4.0, 6.0, 7.5, 8.5, 11.0, 13.0, 15.0, 17.0, 20.0, 24.0, 28.0, 31.0, 38.0]
    pelajes = ["corto", "largo", "rizado", "doble"]
    for m, peso in enumerate(pesos):
        pseudo = f"sim_mascota_{m:02d}"
        pelaje = pelajes[m % len(pelajes)]
        for k in range(3):
            fuente = FUENTE_INSTAGRAM if k == 0 else FUENTE_CAPTURA
            registros.append(
                Registro(
                    id_imagen=f"real_sim_{m:02d}_{k}",
                    fuente=fuente,
                    ruta=f"{fuente}/sim_{m:02d}_{k}.jpg",
                    mascota_id=pseudo,
                    tamano=clasificar_peso(peso),
                    pelaje=pelaje,
                    origen_etiqueta="declarada_por_propietaria",
                    escala_presente=int(rng.random() < 0.5),
                    revision_manual=1,
                )
            )
    return registros


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="SCRUM-101 — preparación del dataset de imágenes")
    ap.add_argument("--stanford", type=Path, help="carpeta Images/ de Stanford Dogs")
    ap.add_argument("--instagram", type=Path, help="fotografías descargadas de Instagram")
    ap.add_argument("--captura", type=Path, help="fotografías de captura estructurada")
    ap.add_argument("--etiquetas", type=Path, help="CSV de etiquetas llenado por la propietaria")
    ap.add_argument("--tarifario", type=Path, help="tarifario_v1.json de SCRUM-98")
    ap.add_argument("--salida", type=Path, default=Path("datos/procesado"))
    ap.add_argument("--simular", action="store_true", help="ejecuta con datos sintéticos")
    ap.add_argument("--semiamplitud", type=float, default=0.10,
                    help="semiamplitud objetivo del IC 95%% (por defecto 0,10)")
    args = ap.parse_args()

    print(">> Integridad de la tabla de razas")
    problemas = integridad_tabla()
    for p in problemas:
        print("   AVISO:", p)
    if problemas:
        print("   Se detiene: corrige la tabla antes de generar el dataset.")
        return 1
    print("   OK: 120 razas, sin duplicados, pelajes dentro de la taxonomía.")

    if args.tarifario:
        print(">> Consistencia con el tarifario de SCRUM-98")
        for p in verificar_contra_tarifario(args.tarifario):
            print("   AVISO:", p)

    filas_mapeo = construir_mapeo()
    mapa = {f["slug"]: f for f in filas_mapeo}
    ruta_mapeo = escribir_csv(Path(__file__).parent / "config" / "mapeo_razas.csv")
    print(f">> Mapeo raza→clase escrito en {ruta_mapeo}")

    args.salida.mkdir(parents=True, exist_ok=True)
    registros: list[Registro] = []

    if args.simular:
        print(">> Modo simulación (no se procesan imágenes reales)")
        registros = simular(args.salida, mapa)
    else:
        try:
            sal = obtener_sal()
        except SalNoConfigurada as e:
            print(f"   {e}")
            return 1

        if args.stanford:
            print(">> Ingiriendo Stanford Dogs")
            registros += ingerir_stanford(args.stanford, mapa, args.salida)
        etiquetas = _leer_etiquetas(args.etiquetas) if args.etiquetas else {}
        for carpeta, fuente in ((args.instagram, FUENTE_INSTAGRAM), (args.captura, FUENTE_CAPTURA)):
            if carpeta:
                print(f">> Ingiriendo {fuente}")
                registros += ingerir_propias(carpeta, fuente, etiquetas, sal, args.salida)
        registros = deduplicar(registros)

    if not registros:
        print("No hay registros que procesar. Indica al menos una fuente o usa --simular.")
        return 1

    print(">> Partición (agrupada por mascota, test solo de dominio real)")
    resumen = particionar(registros)
    for adv in resumen.advertencias:
        print("   AVISO:", adv)

    ruta_manifiesto = escribir_manifiesto(registros, args.salida / "manifiesto.csv")
    print(f"   Manifiesto: {ruta_manifiesto}")

    cob = cobertura(registros)
    brec = brecha(registros, semiamplitud=args.semiamplitud)
    cob_map = cobertura_del_mapeo(filas_mapeo)

    texto = imprimir_reporte(cob, brec, cob_map)
    print()
    print(texto)

    (args.salida / "reporte_cobertura.txt").write_text(texto, encoding="utf-8")
    (args.salida / "reporte_cobertura.json").write_text(
        json.dumps({"cobertura": cob, "brecha": brec, "mapeo": cob_map},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nReportes escritos en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
