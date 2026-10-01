"""
SCRUM-101 — Consolidación del dataset y partición.

DECISIÓN CENTRAL (D4): EL CONJUNTO DE PRUEBA ES SOLO DE DOMINIO REAL
--------------------------------------------------------------------
Stanford Dogs y las fotos que llegan por WhatsApp no son el mismo dominio.
Stanford Dogs proviene de ImageNet: imágenes de la web, bien encuadradas, bien
iluminadas, con el animal centrado y a menudo de ejemplares de exposición.
Lo que enviará una clienta es una foto de celular, recomprimida por WhatsApp,
con el perro en movimiento, a contraluz o sobre un sofá estampado.

Entrenar y evaluar sobre Stanford Dogs mediría la capacidad del modelo de
reconocer perros de catálogo, no de cotizar la mascota de una clienta. La
literatura sobre robustez a corrupciones comunes (Hendrycks y Dietterich, 2019)
documenta caídas sustanciales de exactitud ante desenfoque, ruido y compresión
JPEG, que son precisamente las degradaciones del canal de despliegue.

En consecuencia:
  - `train`: Stanford Dogs (+ fotos propias sobrantes), con aumentación que
    simula la degradación de WhatsApp.
  - `val`:   mezcla, para ajustar hiperparámetros.
  - `test`:  EXCLUSIVAMENTE fotografías propias del negocio, jamás vistas.

El umbral de F1 macro >= 0,85 comprometido en SCRUM-105 solo es defendible si
se mide sobre este `test`. Medido sobre Stanford Dogs sería un número alto y
sin significado.

DECISIÓN (D5): LA PARTICIÓN AGRUPA POR MASCOTA, NO POR IMAGEN
--------------------------------------------------------------
Con ~12 clientes fijos al mes, una misma mascota aparecerá muchas veces. Si dos
fotos del mismo animal caen en lados opuestos de la partición, el modelo
reconoce al individuo y la métrica se infla. Se agrupa por seudónimo de mascota
(el mismo de SCRUM-63), nunca por archivo.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass, asdict, field
from pathlib import Path

from clases import CLAVES_PELAJE, CLAVES_TAMANO

SEMILLA = 42  # la misma de SCRUM-63, para que ambos datasets sean comparables

FUENTE_STANFORD = "stanford_dogs"
FUENTE_INSTAGRAM = "propias_instagram"
FUENTE_CAPTURA = "propias_captura"
FUENTES_DOMINIO_REAL = {FUENTE_INSTAGRAM, FUENTE_CAPTURA}

PROPORCIONES_REAL = {"test": 0.40, "val": 0.20, "train": 0.40}


@dataclass
class Registro:
    """Una fila del manifiesto. El manifiesto, no las carpetas, es el dataset."""
    id_imagen: str
    fuente: str
    ruta: str
    mascota_id: str            # seudónimo HMAC; para Stanford, id sintético
    raza_slug: str = ""
    tamano: str = ""
    pelaje: str = ""
    origen_etiqueta: str = ""  # 'derivada_de_raza' | 'declarada_por_propietaria'
    tamano_ambiguo: int = 0
    escala_presente: int = 0   # ¿la foto incluye un objeto de referencia de escala?
    phash: str = ""
    tenia_gps: int = 0
    revision_manual: int = 0
    particion: str = ""
    observaciones: str = ""


@dataclass
class ResumenParticion:
    total: int = 0
    por_particion: dict = field(default_factory=dict)
    advertencias: list = field(default_factory=list)


def particionar(registros: list[Registro], semilla: int = SEMILLA) -> ResumenParticion:
    """
    Asigna `particion` a cada registro, in place.

    Reglas, en este orden:
      1. Todo lo que venga de Stanford Dogs va a `train`. Nunca a `test`.
      2. Las fotos de dominio real se reparten por MASCOTA, no por imagen.
      3. El reparto se estratifica por la clase conjunta (tamaño, pelaje) de la
         mascota, para que ninguna partición quede sin representantes de una
         clase que existe.
    """
    rng = random.Random(semilla)
    resumen = ResumenParticion()

    reales = [r for r in registros if r.fuente in FUENTES_DOMINIO_REAL]
    sinteticos = [r for r in registros if r.fuente not in FUENTES_DOMINIO_REAL]

    for r in sinteticos:
        r.particion = "train"

    # Agrupar las fotos reales por mascota
    por_mascota: dict[str, list[Registro]] = {}
    for r in reales:
        por_mascota.setdefault(r.mascota_id, []).append(r)

    # Estrato = clase conjunta declarada de la mascota (se toma del primer
    # registro; el protocolo obliga a que sea la misma en todas sus fotos)
    estratos: dict[tuple[str, str], list[str]] = {}
    for mascota, filas in por_mascota.items():
        clave = (filas[0].tamano, filas[0].pelaje)
        estratos.setdefault(clave, []).append(mascota)

    # Estratos demasiado pequeños se agrupan en un estrato residual. Con ~12
    # clientes fijos y 12 clases conjuntas posibles, estratificar por la clase
    # conjunta deja casi todos los estratos con una sola mascota y la partición
    # degenera: no quedaría conjunto de validación. Agrupar los estratos
    # escasos conserva el reparto global aunque sacrifique el balance fino.
    MINIMO_POR_ESTRATO = 3
    residual: list[str] = []
    estratos_utiles: dict[tuple[str, str], list[str]] = {}
    for clave, mascotas in estratos.items():
        if len(mascotas) < MINIMO_POR_ESTRATO:
            residual.extend(mascotas)
        else:
            estratos_utiles[clave] = mascotas
    if residual:
        estratos_utiles[("__residual__", "")] = residual
        resumen.advertencias.append(
            f"{len(residual)} mascotas quedaron en estratos de menos de "
            f"{MINIMO_POR_ESTRATO} individuos y se repartieron como estrato "
            f"residual. El balance por clase conjunta no está garantizado: es "
            f"consecuencia directa del bajo número de clientes, no del algoritmo."
        )

    for clave, mascotas in sorted(estratos_utiles.items()):
        mascotas = sorted(mascotas)
        rng.shuffle(mascotas)
        n = len(mascotas)
        n_test = max(1, round(n * PROPORCIONES_REAL["test"]))
        n_val = max(0, round(n * PROPORCIONES_REAL["val"]))
        if n_test + n_val >= n:
            n_val = max(0, n - n_test - 1)
        asignacion: dict[str, str] = {}
        for i, m in enumerate(mascotas):
            if i < n_test:
                asignacion[m] = "test"
            elif i < n_test + n_val:
                asignacion[m] = "val"
            else:
                asignacion[m] = "train"
        for mascota, particion in asignacion.items():
            for r in por_mascota[mascota]:
                r.particion = particion

    resumen.total = len(registros)
    conteo: dict[str, int] = {}
    for r in registros:
        conteo[r.particion] = conteo.get(r.particion, 0) + 1
    resumen.por_particion = conteo

    resumen.advertencias.extend(verificar_particion(registros))
    return resumen


def verificar_particion(registros: list[Registro]) -> list[str]:
    """Controles que deben pasar antes de dar la historia por terminada."""
    problemas: list[str] = []

    # 1. Ninguna mascota puede estar en dos particiones (fuga por individuo)
    particiones_por_mascota: dict[str, set[str]] = {}
    for r in registros:
        if r.fuente in FUENTES_DOMINIO_REAL:
            particiones_por_mascota.setdefault(r.mascota_id, set()).add(r.particion)
    for mascota, parts in particiones_por_mascota.items():
        if len(parts) > 1:
            problemas.append(f"FUGA: la mascota {mascota} aparece en {sorted(parts)}.")

    # 2. El conjunto de prueba no puede contener imágenes sintéticas
    intrusos = [r.id_imagen for r in registros
                if r.particion == "test" and r.fuente not in FUENTES_DOMINIO_REAL]
    if intrusos:
        problemas.append(
            f"CONTAMINACIÓN: {len(intrusos)} imágenes que no son de dominio real "
            f"cayeron en test. La métrica de SCRUM-105 quedaría inflada."
        )

    # 3. Toda imagen de dominio real debe haber pasado revisión manual
    sin_revisar = [r.id_imagen for r in registros
                   if r.fuente in FUENTES_DOMINIO_REAL and not r.revision_manual]
    if sin_revisar:
        problemas.append(
            f"PROTOCOLO: {len(sin_revisar)} fotografías propias sin revisión manual. "
            f"La revisión del 100 % es paso obligatorio, no opcional."
        )

    # 4. Etiquetas dentro de la taxonomía
    for r in registros:
        if r.tamano and r.tamano not in CLAVES_TAMANO:
            problemas.append(f"{r.id_imagen}: tamaño '{r.tamano}' fuera de taxonomía.")
        if r.pelaje and r.pelaje not in CLAVES_PELAJE:
            problemas.append(f"{r.id_imagen}: pelaje '{r.pelaje}' fuera de taxonomía.")

    return problemas


def escribir_manifiesto(registros: list[Registro], destino: str | Path) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    campos = list(asdict(registros[0]).keys()) if registros else [f.name for f in Registro.__dataclass_fields__.values()]
    with destino.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        for r in registros:
            w.writerow(asdict(r))
    return destino


def leer_manifiesto(origen: str | Path) -> list[Registro]:
    with Path(origen).open(encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    enteros = {"tamano_ambiguo", "escala_presente", "tenia_gps", "revision_manual"}
    salida = []
    for f in filas:
        for k in enteros:
            f[k] = int(f.get(k) or 0)
        salida.append(Registro(**f))
    return salida
