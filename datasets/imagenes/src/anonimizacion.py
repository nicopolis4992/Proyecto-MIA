"""
SCRUM-101 — Anonimización de las fotografías y control de duplicados.

MARCO LEGAL
-----------
Ley Orgánica de Protección de Datos Personales del Ecuador (LOPDP, R.O. Supl.
459, 2021). Una fotografía de una mascota no es, por sí misma, un dato personal
del cliente; sí lo son los metadatos que la acompañan (coordenadas GPS del
domicilio, identificador del dispositivo, fecha y hora) y cualquier persona que
aparezca en el encuadre. La LOPDP distingue seudonimización de disociación: lo
que aquí se aplica a los identificadores es SEUDONIMIZACIÓN, coherente con la
decisión ya tomada en SCRUM-63.

POR QUÉ SEUDONIMIZAR Y NO ANONIMIZAR DIRECTAMENTE
-------------------------------------------------
Se necesita que una misma mascota reciba siempre el mismo seudónimo, por tres
razones operativas:
  1. agrupar todas las fotos de un mismo animal para impedir que aparezcan a la
     vez en entrenamiento y en prueba (fuga de datos);
  2. enlazar la fotografía con la conversación de WhatsApp del mismo cliente en
     el dataset de SCRUM-63, que usa exactamente el mismo mecanismo y la misma
     sal;
  3. permitir que la propietaria corrija una etiqueta equivocada sin tener que
     re-identificar al animal a mano.

La anonimización plena se alcanza destruyendo la sal al cierre del proyecto.

DECISIÓN: la sal NUNCA se versiona. Se lee de la variable de entorno
`MIA_SAL_SEUDONIMO`. Si falta, el pipeline se detiene: es preferible no producir
dataset a producir uno con seudónimos reproducibles por terceros.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

try:
    import imagehash
except ImportError:  # pragma: no cover
    imagehash = None


VAR_SAL = "MIA_SAL_SEUDONIMO"
LONGITUD_SEUDONIMO = 16  # caracteres hexadecimales

# Campos EXIF cuya sola presencia obliga a dejar constancia en el registro de
# tratamiento. GPSInfo es el crítico: en fotos tomadas en el domicilio del
# cliente equivale a su dirección.
CAMPOS_SENSIBLES = {
    0x8825: "GPSInfo",
    0x010F: "Make",
    0x0110: "Model",
    0x0132: "DateTime",
    0x9003: "DateTimeOriginal",
    0xA430: "CameraOwnerName",
    0xA431: "BodySerialNumber",
    0x013B: "Artist",
    0x8298: "Copyright",
}


class SalNoConfigurada(RuntimeError):
    pass


def obtener_sal() -> bytes:
    sal = os.environ.get(VAR_SAL)
    if not sal:
        raise SalNoConfigurada(
            f"La variable de entorno {VAR_SAL} no está definida. "
            "El pipeline no genera seudónimos sin sal secreta."
        )
    return sal.encode("utf-8")


def seudonimo(identificador: str, sal: bytes | None = None) -> str:
    """
    Seudónimo determinista HMAC-SHA256. Mismo mecanismo que SCRUM-63: el mismo
    identificador y la misma sal producen siempre el mismo seudónimo, y sin la
    sal el seudónimo no es reversible por fuerza bruta sobre el espacio de
    números telefónicos ecuatorianos (que es pequeño y sí sería vulnerable a un
    hash simple sin clave).
    """
    sal = sal if sal is not None else obtener_sal()
    normalizado = identificador.strip().lower()
    return hmac.new(sal, normalizado.encode("utf-8"), hashlib.sha256).hexdigest()[:LONGITUD_SEUDONIMO]


@dataclass
class ResultadoLimpieza:
    destino: Path
    campos_hallados: list[str]
    tenia_gps: bool
    ancho: int
    alto: int


def limpiar_metadatos(origen: str | Path, destino: str | Path, calidad: int = 95) -> ResultadoLimpieza:
    """
    Reescribe la imagen sin ningún metadato.

    No se "borran" campos uno a uno: se vuelca únicamente la matriz de píxeles
    a un archivo nuevo, de modo que no puede sobrevivir ningún segmento EXIF,
    XMP o IPTC. Antes de descartarlos se deja constancia de qué campos
    sensibles existían, porque el registro de actividades de tratamiento que
    exige la LOPDP debe poder demostrar qué se recibió y qué se eliminó.
    """
    origen, destino = Path(origen), Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(origen) as img:
        hallados: list[str] = []
        exif = img.getexif() if hasattr(img, "getexif") else None
        if exif:
            for etiqueta, nombre in CAMPOS_SENSIBLES.items():
                if etiqueta in exif:
                    hallados.append(nombre)
        ancho, alto = img.size
        limpia = Image.new(img.mode if img.mode in ("RGB", "L") else "RGB", img.size)
        limpia.putdata(list(img.convert(limpia.mode).getdata()))
        limpia.save(destino, format="JPEG", quality=calidad, optimize=True)

    return ResultadoLimpieza(
        destino=destino,
        campos_hallados=hallados,
        tenia_gps="GPSInfo" in hallados,
        ancho=ancho,
        alto=alto,
    )


def hash_perceptual(ruta: str | Path) -> str:
    """pHash de 64 bits. Robusto a recompresión y reescalado, que es exactamente
    lo que hace WhatsApp al reenviar una imagen."""
    if imagehash is None:  # pragma: no cover
        raise RuntimeError("Falta la dependencia 'imagehash' (pip install imagehash).")
    with Image.open(ruta) as img:
        return str(imagehash.phash(img))


def distancia_hamming(h1: str, h2: str) -> int:
    a = int(h1, 16)
    b = int(h2, 16)
    return bin(a ^ b).count("1")


def agrupar_duplicados(hashes: dict[str, str], umbral: int = 5) -> list[list[str]]:
    """
    Agrupa imágenes casi idénticas. Umbral 5 sobre 64 bits es el valor habitual
    para considerar dos imágenes "la misma foto" tras recompresión.

    Importa porque las fotos de Instagram del negocio suelen reciclarse: la
    misma mascota publicada dos veces con recorte distinto inflaría el conjunto
    y, si cae a ambos lados de la partición, produciría fuga.
    """
    claves = list(hashes.keys())
    visitados: set[str] = set()
    grupos: list[list[str]] = []
    for i, k in enumerate(claves):
        if k in visitados:
            continue
        grupo = [k]
        visitados.add(k)
        for k2 in claves[i + 1:]:
            if k2 in visitados:
                continue
            if distancia_hamming(hashes[k], hashes[k2]) <= umbral:
                grupo.append(k2)
                visitados.add(k2)
        if len(grupo) > 1:
            grupos.append(grupo)
    return grupos
