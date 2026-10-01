"""
Control de calidad de la fotografia antes de clasificar (SCRUM-104).

Se rechazan fotos que ningun clasificador puede resolver bien: muy pequenas,
muy oscuras/sobreexpuestas o borrosas. Es mas barato y mas honesto pedir
otra foto que devolver una cotizacion basada en una prediccion sin sustento.

La nitidez se mide con la varianza del Laplaciano (Pech-Pacheco et al.,
2000), calculada sobre la imagen en escala de grises reducida a 512 px para
que el umbral no dependa de la resolucion original.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps


@dataclass
class EvaluacionCalidad:
    aceptable: bool
    motivo: str | None
    lado_menor_px: int
    brillo_medio: float
    nitidez: float


def cargar_imagen(datos: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(datos))
    return ImageOps.exif_transpose(img).convert("RGB")


def evaluar_calidad(datos: bytes, umbrales: dict) -> EvaluacionCalidad:
    try:
        img = cargar_imagen(datos)
    except Exception:  # noqa: BLE001 - cualquier archivo ilegible es "no aceptable"
        return EvaluacionCalidad(False, "ilegible", 0, 0.0, 0.0)

    lado_menor = min(img.size)
    gris = img.convert("L")
    gris.thumbnail((512, 512))
    a = np.asarray(gris, dtype=np.float32)
    brillo = float(a.mean())
    lap = a[1:-1, :-2] + a[1:-1, 2:] + a[:-2, 1:-1] + a[2:, 1:-1] - 4 * a[1:-1, 1:-1]
    nitidez = float(lap.var())

    motivo = None
    if lado_menor < umbrales["lado_menor_min_px"]:
        motivo = "pequena"
    elif brillo < umbrales["brillo_min"]:
        motivo = "oscura"
    elif brillo > umbrales["brillo_max"]:
        motivo = "sobreexpuesta"
    elif nitidez < umbrales["nitidez_min"]:
        motivo = "borrosa"

    return EvaluacionCalidad(motivo is None, motivo, lado_menor, round(brillo, 1), round(nitidez, 1))
