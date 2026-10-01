"""
SCRUM-101 — Definición de las clases objetivo del dataset de imágenes.

Las clases NO se inventan aquí: son exactamente los parámetros que consume el
tarifario parametrizado de SCRUM-98 (`tarifario_v1.json`). Cualquier divergencia
entre este módulo y el tarifario rompe la cadena SCRUM-101 -> SCRUM-102 ->
SCRUM-103, por lo que `verificar_contra_tarifario()` debe ejecutarse en cuanto
el archivo del tarifario esté disponible.

Decisión de diseño D1: se predicen DOS variables independientes (tamaño y
pelaje), no una sola clase combinada de 12 categorías. Razón: el tarifario las
usa como factores multiplicativos separados, y una clase combinada exigiría
cobertura simultánea de las 12 celdas, inalcanzable con el volumen de
fotografías reales que produce un negocio de ~12 clientes fijos al mes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path


# --------------------------------------------------------------------------
# Tamaño: cortes por peso vivo, tomados de SCRUM-98
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ClaseTamano:
    clave: str
    etiqueta: str
    peso_min_kg: float
    peso_max_kg: float


CLASES_TAMANO: tuple[ClaseTamano, ...] = (
    ClaseTamano("pequeno", "Pequeño", 0.0, 9.0),
    ClaseTamano("mediano", "Mediano", 9.1, 18.0),
    ClaseTamano("grande", "Grande", 18.1, 45.0),
)

# Fuera de rango: el tarifario v1 no cotiza por encima de 45 kg. No es un error
# del dataset sino un límite declarado del servicio; estas razas se etiquetan
# como `fuera_de_rango` y se excluyen del entrenamiento supervisado de tamaño.
CLAVE_FUERA_DE_RANGO = "fuera_de_rango"


# --------------------------------------------------------------------------
# Pelaje: cuatro tipos con factor multiplicativo, tomados de SCRUM-98
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ClasePelaje:
    clave: str
    etiqueta: str
    factor: float


CLASES_PELAJE: tuple[ClasePelaje, ...] = (
    ClasePelaje("corto", "Corto", 1.00),
    ClasePelaje("doble", "Doble / denso", 1.15),
    ClasePelaje("largo", "Largo", 1.20),
    ClasePelaje("rizado", "Rizado / lanudo", 1.25),
)

# HALLAZGO ABIERTO (ver anexo metodológico, sección 4.3):
# la taxonomía de cuatro pelajes del tarifario v1 no contempla el pelo DURO
# (wiry / de arranque), propio de terriers y schnauzers, que es de los más
# costosos en tiempo de grooming. Mientras SCRUM-98 no incorpore una quinta
# categoría, estas razas se asignan provisionalmente a `doble` y quedan
# marcadas en la columna `pelaje_observacion` del mapeo.
PELAJE_NO_CUBIERTO = "duro"


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

CLAVES_TAMANO = tuple(c.clave for c in CLASES_TAMANO)
CLAVES_PELAJE = tuple(c.clave for c in CLASES_PELAJE)


def clasificar_peso(peso_kg: float) -> str:
    """Devuelve la clave de tamaño para un peso puntual en kilogramos."""
    for c in CLASES_TAMANO:
        if c.peso_min_kg <= peso_kg <= c.peso_max_kg:
            return c.clave
    return CLAVE_FUERA_DE_RANGO


def clasificar_rango_peso(peso_min_kg: float, peso_max_kg: float) -> tuple[str, bool]:
    """
    Clasifica un RANGO de peso (el estándar de una raza, no un individuo).

    Devuelve (clave_de_tamano, es_ambiguo). Es ambiguo cuando el rango cruza
    al menos un corte del tarifario: en ese caso la raza no determina la clase
    y la etiqueta derivada no es utilizable como verdad de campo.
    """
    clave_min = clasificar_peso(peso_min_kg)
    clave_max = clasificar_peso(peso_max_kg)
    if clave_min != clave_max:
        return clave_max, True
    return clave_min, False


def verificar_contra_tarifario(ruta_tarifario: str | Path) -> list[str]:
    """
    Contrasta las clases de este módulo con `tarifario_v1.json` de SCRUM-98.

    Devuelve la lista de discrepancias encontradas. Lista vacía = consistente.
    Esta función es el control que impide que el dataset se construya sobre
    clases que el motor de cotización no sabe consumir.
    """
    ruta = Path(ruta_tarifario)
    if not ruta.exists():
        return [f"No se encontró el tarifario en {ruta}. Verificación no ejecutada."]

    tarifario = json.loads(ruta.read_text(encoding="utf-8"))
    problemas: list[str] = []

    tamanos_tarifario = set(_buscar_claves(tarifario, NOMBRES_TAMANO))
    pelajes_tarifario = set(_buscar_claves(tarifario, NOMBRES_PELAJE))

    if tamanos_tarifario and tamanos_tarifario != set(CLAVES_TAMANO):
        problemas.append(
            f"Clases de tamaño divergentes. Dataset: {sorted(CLAVES_TAMANO)} | "
            f"Tarifario: {sorted(tamanos_tarifario)}"
        )
    if pelajes_tarifario and pelajes_tarifario != set(CLAVES_PELAJE):
        problemas.append(
            f"Clases de pelaje divergentes. Dataset: {sorted(CLAVES_PELAJE)} | "
            f"Tarifario: {sorted(pelajes_tarifario)}"
        )

    # Mismo nombre no basta: el factor y los cortes de peso también deben
    # coincidir, o el clasificador y el motor cotizan con reglas distintas.
    for c in CLASES_TAMANO:
        item = _buscar_items(tarifario, NOMBRES_TAMANO).get(c.clave)
        if item and "peso_kg_min" in item and "peso_kg_max" in item:
            if (float(item["peso_kg_min"]), float(item["peso_kg_max"])) != (c.peso_min_kg, c.peso_max_kg):
                problemas.append(
                    f"Cortes de peso divergentes para '{c.clave}'. Dataset: "
                    f"{c.peso_min_kg}–{c.peso_max_kg} kg | Tarifario: "
                    f"{item['peso_kg_min']}–{item['peso_kg_max']} kg"
                )
    for c in CLASES_PELAJE:
        item = _buscar_items(tarifario, NOMBRES_PELAJE).get(c.clave)
        if item and "factor" in item and float(item["factor"]) != c.factor:
            problemas.append(
                f"Factor de pelaje divergente para '{c.clave}'. Dataset: {c.factor} | "
                f"Tarifario: {item['factor']}"
            )
    if not tamanos_tarifario and not pelajes_tarifario:
        problemas.append(
            "No se hallaron claves de tamaño ni de pelaje en el tarifario; "
            "revisar manualmente la estructura del archivo."
        )
    return problemas


# Nombres bajo los que el tarifario puede declarar cada dimensión.
# `tarifario_v1.json` usa `clasificacion_tamano` / `clasificacion_pelaje`.
NOMBRES_TAMANO = ("tamano", "tamaño", "tamanos", "tamaños", "clasificacion_tamano")
NOMBRES_PELAJE = ("pelaje", "pelajes", "clasificacion_pelaje")
CAMPOS_CLAVE = ("codigo", "clave", "id", "nombre", "tipo")


def _buscar_items(nodo, nombres: tuple[str, ...]) -> dict[str, dict]:
    """Devuelve {clave: item} de las listas de objetos declaradas bajo `nombres`."""
    items: dict[str, dict] = {}
    if isinstance(nodo, dict):
        for k, v in nodo.items():
            if k.lower() in nombres and isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        campo = next((c for c in CAMPOS_CLAVE if c in item), None)
                        if campo:
                            items[str(item[campo]).lower()] = item
            else:
                items.update(_buscar_items(v, nombres))
    elif isinstance(nodo, list):
        for item in nodo:
            items.update(_buscar_items(item, nombres))
    return items


def _buscar_claves(nodo, nombres: tuple[str, ...]) -> list[str]:
    """Recorre el JSON del tarifario buscando el diccionario de una dimensión."""
    hallados: list[str] = []
    if isinstance(nodo, dict):
        for k, v in nodo.items():
            if k.lower() in nombres and isinstance(v, dict):
                hallados.extend(str(x).lower() for x in v.keys())
            elif k.lower() in nombres and isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        for campo in CAMPOS_CLAVE:
                            if campo in item:
                                hallados.append(str(item[campo]).lower())
                                break
                    else:
                        hallados.append(str(item).lower())
            else:
                hallados.extend(_buscar_claves(v, nombres))
    elif isinstance(nodo, list):
        for item in nodo:
            hallados.extend(_buscar_claves(item, nombres))
    return hallados


def resumen() -> dict:
    return {
        "tamano": [asdict(c) for c in CLASES_TAMANO],
        "pelaje": [asdict(c) for c in CLASES_PELAJE],
    }


if __name__ == "__main__":
    print(json.dumps(resumen(), ensure_ascii=False, indent=2))
