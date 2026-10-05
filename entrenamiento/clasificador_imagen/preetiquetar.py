"""
SCRUM-101/102 — Pre-etiquetado del dataset de Facebook con Gemini + revisión humana.

El dataset de fotos propias (dataset_fb_v1, 312 imágenes) no tiene etiquetas de
tamaño, grupo de manto ni estado del pelo, y sin ellas no se puede entrenar la
CNN. Este script propone etiquetas con Gemini (el mismo clasificador zero-shot
del prototipo) para que el EQUIPO las revise y corrija; no reemplaza la
revisión humana.

Dos pasos:

1) Proponer etiquetas (llama a Gemini, ~1 s por imagen):
    python -m entrenamiento.clasificador_imagen.preetiquetar proponer \
        --dataset READ/Dataset_FB_v1_SCRUM101_parte1/dataset_fb_v1 \
        --imagenes READ/Dataset_FB_v1_SCRUM101_parte2/dataset_fb_v1/imagenes \
        --salida READ/etiquetas_propuestas.csv
   Abrir el CSV en Excel y revisar cada fila: corregir tamano / grupo /
   estado si hace falta y poner `revisado` = si. Las filas dudosas
   (confianza baja) vienen primero.

2) Construir el manifiesto de entrenamiento (sin llamadas a Gemini):
    python -m entrenamiento.clasificador_imagen.preetiquetar manifiesto \
        --etiquetas READ/etiquetas_propuestas.csv --salida READ/manifiesto_v2.csv
   Solo entran filas con revisado = si. La partición agrupa por mascota
   (id_mascota_prov, semilla 42) para que el mismo perro no quede en
   entrenamiento y prueba a la vez.

Cuidado metodológico (para el informe): si las etiquetas no se revisan, la
CNN aprende a imitar a Gemini (destilación), no a la propietaria. Las fotos
DESPUÉS casi siempre están sin nudos y con pañoleta: el estado se aprende de
las fotos ANTES.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

COLUMNAS = ["id_imagen", "ruta", "id_mascota_prov", "momento", "nombre_leido", "varios_animales",
            "tamano", "conf_tamano", "grupo", "conf_grupo", "estado", "conf_estado",
            "es_perro", "observacion", "revisado"]
UMBRAL_REVISAR = 0.75


def _buscar_imagen(id_imagen: str, carpetas: list[Path]) -> Path | None:
    for c in carpetas:
        p = c / f"{id_imagen}.jpg"
        if p.exists():
            return p
    return None


def proponer(dataset: Path, imagenes_extra: list[Path], salida: Path, limite: int | None) -> None:
    from app.config import crear_cliente_gemini
    from app.vision.clasificador import ClasificadorGemini

    clasificador = ClasificadorGemini(crear_cliente_gemini())
    filas = list(csv.DictReader(open(dataset / "manifiesto.csv", encoding="utf-8")))
    carpetas = [dataset / "imagenes", *imagenes_extra]
    hechas = {}
    if salida.exists():  # se puede reanudar si se corta
        hechas = {f["id_imagen"]: f for f in csv.DictReader(open(salida, encoding="utf-8-sig"))}

    resultado = []
    for i, f in enumerate(filas[:limite] if limite else filas, 1):
        if f["id_imagen"] in hechas:
            resultado.append(hechas[f["id_imagen"]])
            continue
        ruta = _buscar_imagen(f["id_imagen"], carpetas)
        if ruta is None:
            print(f"  sin archivo: {f['id_imagen']}")
            continue
        try:
            c = clasificador.clasificar(ruta.read_bytes())
        except Exception as exc:  # noqa: BLE001 - se sigue con las demas
            print(f"  error en {f['id_imagen']}: {exc}")
            continue
        resultado.append({
            # Ruta relativa a una carpeta con TODAS las imagenes juntas (parte 1 + 2),
            # que es como se sube a Google Drive para Colab.
            "id_imagen": f["id_imagen"], "ruta": f"imagenes/{ruta.name}",
            "id_mascota_prov": f["id_mascota_prov"], "momento": f["momento"],
            "nombre_leido": f["nombre_leido"], "varios_animales": f["varios_animales"],
            "tamano": c.tamano, "conf_tamano": round(c.confianza_tamano, 2),
            "grupo": c.grupo, "conf_grupo": round(c.confianza_grupo, 2),
            # Las fotos DESPUES muestran al perro ya arreglado: su estado no
            # informa del manto real y se deja vacio para no sesgar la cabeza.
            "estado": c.estado if f["momento"] != "despues" else "",
            "conf_estado": round(c.confianza_estado, 2) if f["momento"] != "despues" else "",
            "es_perro": "si" if c.es_perro else "no", "observacion": c.observacion or "",
            "revisado": "",
        })
        print(f"[{i}/{len(filas)}] {f['id_imagen']}: {c.tamano} ({c.confianza_tamano:.2f}) "
              f"{c.grupo} ({c.confianza_grupo:.2f}) {c.estado}")
        time.sleep(0.2)

    # Las dudosas primero: es donde la revision humana aporta mas.
    def prioridad(r):
        confs = [float(r[k]) for k in ("conf_tamano", "conf_grupo") if r.get(k) not in ("", None)]
        return min(confs) if confs else 0
    resultado.sort(key=prioridad)
    with open(salida, "w", newline="", encoding="utf-8-sig") as fh:  # utf-8-sig: Excel lo abre bien
        w = csv.DictWriter(fh, fieldnames=COLUMNAS)
        w.writeheader()
        w.writerows(resultado)
    dudosas = sum(1 for r in resultado if prioridad(r) < UMBRAL_REVISAR)
    print(f"\n{len(resultado)} filas en {salida}. {dudosas} con confianza < {UMBRAL_REVISAR}: revisarlas primero.")


def manifiesto(etiquetas: Path, salida: Path, semilla: int = 42) -> None:
    filas = [f for f in csv.DictReader(open(etiquetas, encoding="utf-8-sig"))
             if f.get("revisado", "").strip().lower() in ("si", "sí", "x", "1")
             and f.get("es_perro", "si") == "si" and f.get("varios_animales", "") not in ("si", "1")]
    if not filas:
        raise SystemExit("No hay filas con revisado = si. Revisar el CSV primero.")

    # Particion agrupada por mascota: 70 / 15 / 15.
    mascotas = sorted({f["id_mascota_prov"] for f in filas})
    random.Random(semilla).shuffle(mascotas)
    n = len(mascotas)
    corte_val, corte_test = int(n * 0.70), int(n * 0.85)
    particion = {m: ("train" if i < corte_val else "val" if i < corte_test else "test")
                 for i, m in enumerate(mascotas)}

    with open(salida, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["ruta", "fuente", "mascota_id", "tamano", "tamano_ambiguo",
                                           "grupo", "estado", "particion"])
        w.writeheader()
        for f in filas:
            w.writerow({"ruta": f["ruta"], "fuente": "propias_facebook", "mascota_id": f["id_mascota_prov"],
                        "tamano": f["tamano"], "tamano_ambiguo": "0", "grupo": f["grupo"],
                        "estado": f["estado"], "particion": particion[f["id_mascota_prov"]]})
    conteo = {p: sum(1 for f in filas if particion[f["id_mascota_prov"]] == p) for p in ("train", "val", "test")}
    print(f"Manifiesto: {len(filas)} imagenes de {n} mascotas -> {conteo}. Guardado en {salida}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("proponer")
    p.add_argument("--dataset", type=Path, required=True, help="carpeta con manifiesto.csv e imagenes/")
    p.add_argument("--imagenes", type=Path, action="append", default=[], help="carpetas extra de imagenes")
    p.add_argument("--salida", type=Path, required=True)
    p.add_argument("--limite", type=int)
    m = sub.add_parser("manifiesto")
    m.add_argument("--etiquetas", type=Path, required=True)
    m.add_argument("--salida", type=Path, required=True)
    args = ap.parse_args()
    if args.cmd == "proponer":
        proponer(args.dataset, args.imagenes, args.salida, args.limite)
    else:
        manifiesto(args.etiquetas, args.salida)


if __name__ == "__main__":
    main()
