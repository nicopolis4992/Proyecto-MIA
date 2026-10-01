"""
SCRUM-101 — Simulación de la degradación que introduce WhatsApp.

Por qué existe este módulo: el modelo de SCRUM-102 se entrenará mayormente con
imágenes limpias de Stanford Dogs, pero recibirá imágenes que WhatsApp ya
recomprimió. Aumentar el entrenamiento con esa misma degradación es la forma
barata de reducir la brecha de dominio sin conseguir más fotos reales.

No sustituye a las fotografías propias: reduce la brecha, no la cierra. El
conjunto de prueba sigue siendo exclusivamente de dominio real.

Las transformaciones replican lo que hace el canal, no corrupciones arbitrarias:
WhatsApp reescala el lado mayor y recomprime en JPEG con calidad media, y el
usuario aporta desenfoque de movimiento, subexposición y encuadres descentrados.
Referencia metodológica: Hendrycks y Dietterich (2019), que sistematizan
desenfoque, ruido y compresión JPEG como corrupciones de referencia.
"""

from __future__ import annotations

import io
import random
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

LADO_MAYOR_WHATSAPP = 1600   # px; reescalado típico del canal
CALIDAD_JPEG = (65, 85)      # rango de recompresión observable


def recomprimir(img: Image.Image, calidad: int) -> Image.Image:
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="JPEG", quality=calidad)
    buffer.seek(0)
    return Image.open(buffer).copy()


def reescalar_canal(img: Image.Image, lado_mayor: int = LADO_MAYOR_WHATSAPP) -> Image.Image:
    w, h = img.size
    if max(w, h) <= lado_mayor:
        return img
    escala = lado_mayor / max(w, h)
    return img.resize((int(w * escala), int(h * escala)), Image.LANCZOS)


def degradar(img: Image.Image, rng: random.Random | None = None) -> Image.Image:
    """Aplica una degradación aleatoria compatible con el canal de despliegue."""
    rng = rng or random.Random()
    salida = reescalar_canal(img)

    if rng.random() < 0.5:
        salida = salida.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.4, 1.6)))

    if rng.random() < 0.6:
        factor = rng.uniform(0.55, 1.35)  # subexposición o contraluz
        salida = ImageEnhance.Brightness(salida).enhance(factor)

    if rng.random() < 0.4:
        salida = ImageEnhance.Contrast(salida).enhance(rng.uniform(0.7, 1.2))

    if rng.random() < 0.5:  # encuadre descentrado
        w, h = salida.size
        dx, dy = int(w * rng.uniform(0, 0.12)), int(h * rng.uniform(0, 0.12))
        salida = salida.crop((dx, dy, w - int(w * rng.uniform(0, 0.08)), h - int(h * rng.uniform(0, 0.08))))

    return recomprimir(salida, rng.randint(*CALIDAD_JPEG))


def generar_variantes(origen: str | Path, carpeta_destino: str | Path,
                      n: int = 3, semilla: int = 42) -> list[Path]:
    """Genera n variantes degradadas de una imagen, de forma reproducible."""
    origen, carpeta_destino = Path(origen), Path(carpeta_destino)
    carpeta_destino.mkdir(parents=True, exist_ok=True)
    rng = random.Random(f"{semilla}:{origen.name}")
    generadas: list[Path] = []
    with Image.open(origen) as img:
        base = img.convert("RGB")
        for i in range(n):
            destino = carpeta_destino / f"{origen.stem}__deg{i}.jpg"
            degradar(base, rng).save(destino, format="JPEG", quality=90)
            generadas.append(destino)
    return generadas
