"""
SCRUM-101 — Definición de las clases objetivo del dataset de imágenes.

Las clases NO se inventan aquí: son exactamente los parámetros que consume el
tarifario de SCRUM-98, versión 2 (`app/cotizacion/tarifario_v2.json`). Cualquier
divergencia entre este módulo y el tarifario rompe la cadena SCRUM-101 ->
SCRUM-102 -> SCRUM-103, por lo que `verificar_contra_tarifario()` se ejecuta en
las pruebas contra el tarifario real del repositorio.

CAMBIO v1 -> v2 (06/10/2026)
----------------------------
El tarifario v1 cobraba por TIPO DE PELAJE (corto, doble, largo, rizado) con un
factor multiplicativo. Las respuestas de la propietaria mostraron que el precio
no depende del tipo de pelo como tal, sino de la TÉCNICA de manejo del manto que
define la raza (máquina, deslanado, cepillado o solo baño) y del ESTADO del pelo
(con o sin motas). El tarifario v2 reemplazó el eje de pelaje por esas dos
variables y este módulo las replica:

  - tamaño (3):          pequeno / mediano / grande
  - grupo de manto (4):  A_maquina / B_deslanado / C_cepillado / D_corto
  - estado del pelo (3): sin_motas / moderado / severo

La antigua categoría pendiente de "pelo duro" (terriers, schnauzer) desaparece:
la propietaria ubica al schnauzer en el grupo A (se pasa máquina), y por
analogía los terriers de pelo duro van al mismo grupo.

Decisión de diseño D1 (se mantiene): se predicen variables INDEPENDIENTES, una
cabeza por variable, no una clase combinada (3 x 4 x 3 = 36 celdas), que sería
inalcanzable con el volumen de fotografías de un negocio de ~12 clientes fijos
al mes.

El estado del pelo NO se puede derivar de la raza: solo lo aportan fotografías
propias etiquetadas una por una. Stanford Dogs no tiene etiqueta de estado.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

# Tarifario vigente del repositorio (fuente de verdad de las clases).
RUTA_TARIFARIO_V2 = Path(__file__).resolve().parents[3] / "app" / "cotizacion" / "tarifario_v2.json"


# --------------------------------------------------------------------------
# Tamaño: cortes por peso vivo, tomados del tarifario v2
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ClaseTamano:
    clave: str
    etiqueta: str
    peso_min_kg: float
    peso_max_kg: float


# Igual que el tarifario v2: se clasifica por LÍMITE SUPERIOR (peso <= máximo),
# así no quedan huecos entre rangos. En v1 los cortes eran 9,0 / 9,1 y un perro
# de 9,05 kg quedaba "fuera de rango"; ese hueco ya no existe.
CLASES_TAMANO: tuple[ClaseTamano, ...] = (
    ClaseTamano("pequeno", "Pequeño", 0.0, 9.0),
    ClaseTamano("mediano", "Mediano", 9.01, 18.0),
    ClaseTamano("grande", "Grande", 18.01, 45.0),
)

# Fuera de rango: el tarifario no cotiza por encima de 45 kg. No es un error
# del dataset sino un límite declarado del servicio; estas razas se etiquetan
# como `fuera_de_rango` y se excluyen del entrenamiento supervisado de tamaño.
CLAVE_FUERA_DE_RANGO = "fuera_de_rango"


# --------------------------------------------------------------------------
# Grupo de manto: técnica de grooming que define la raza (tarifario v2)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ClaseGrupo:
    clave: str
    etiqueta: str
    descripcion: str


CLASES_GRUPO: tuple[ClaseGrupo, ...] = (
    ClaseGrupo("A_maquina", "A · Máquina", "Pelo de crecimiento continuo; se pasa máquina"),
    ClaseGrupo("B_deslanado", "B · Deslanado", "Doble capa; no se pasa máquina; se hace deslanado"),
    ClaseGrupo("C_cepillado", "C · Cepillado", "Pelo largo sin máquina; mucho cepillado; corte a tijera"),
    ClaseGrupo("D_corto", "D · Corto", "Pelo corto; sin máquina; esencialmente baño"),
)


# --------------------------------------------------------------------------
# Estado del pelo: recargo propio en el tarifario v2
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ClaseEstado:
    clave: str
    etiqueta: str
    descripcion: str


CLASES_ESTADO: tuple[ClaseEstado, ...] = (
    ClaseEstado("sin_motas", "Sin motas", "Pelo sin nudos; no lleva recargo"),
    ClaseEstado("moderado", "Moderado", "Algunos nudos o motas; recargo intermedio"),
    ClaseEstado("severo", "Severo", "Pelo muy enredado pero recuperable; desenredo largo"),
)

# El tarifario v2 contempla un cuarto caso, `no_recuperable` (se rapa en vez de
# desenredar y el precio lo pone la propietaria). No es una clase del
# clasificador: es una decisión de la propietaria al ver al perro, y en las
# fotos es indistinguible de un `severo` extremo. Si aparece en una etiqueta se
# trata como `severo` y se anota en observaciones.
ESTADO_FUERA_DEL_CLASIFICADOR = "no_recuperable"


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

CLAVES_TAMANO = tuple(c.clave for c in CLASES_TAMANO)
CLAVES_GRUPO = tuple(c.clave for c in CLASES_GRUPO)
CLAVES_ESTADO = tuple(c.clave for c in CLASES_ESTADO)


def clasificar_peso(peso_kg: float) -> str:
    """Devuelve la clave de tamaño para un peso puntual en kilogramos."""
    if peso_kg <= 0:
        return CLAVE_FUERA_DE_RANGO
    for c in CLASES_TAMANO:
        if peso_kg <= c.peso_max_kg:
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


def _claves_sin_metadatos(d: dict) -> set[str]:
    """Claves de una sección del tarifario, sin las notas (`_nota`, `_uso`...)."""
    return {k for k in d if not k.startswith("_")}


def verificar_contra_tarifario(ruta_tarifario: str | Path = RUTA_TARIFARIO_V2) -> list[str]:
    """
    Contrasta las clases de este módulo con el tarifario v2 de SCRUM-98.

    Devuelve la lista de discrepancias encontradas. Lista vacía = consistente.
    Es el control que impide que el dataset se construya sobre clases que el
    motor de cotización no sabe consumir.
    """
    ruta = Path(ruta_tarifario)
    if not ruta.exists():
        return [f"No se encontró el tarifario en {ruta}. Verificación no ejecutada."]

    t = json.loads(ruta.read_text(encoding="utf-8"))
    problemas: list[str] = []
    for seccion in ("tamanos", "grupos_manto", "recargo_estado_manto"):
        if not isinstance(t.get(seccion), dict):
            problemas.append(f"El tarifario no tiene la sección '{seccion}' (¿es un tarifario v1?).")
    if problemas:
        return problemas

    # 1. Tamaño: mismas claves y mismos cortes de peso
    tamanos = _claves_sin_metadatos(t["tamanos"])
    if tamanos != set(CLAVES_TAMANO):
        problemas.append(f"Clases de tamaño divergentes. Dataset: {sorted(CLAVES_TAMANO)} | "
                         f"Tarifario: {sorted(tamanos)}")
    for c in CLASES_TAMANO:
        rango = (t["tamanos"].get(c.clave) or {}).get("peso_kg")
        if rango and (float(rango[0]), float(rango[1])) != (c.peso_min_kg, c.peso_max_kg):
            problemas.append(f"Cortes de peso divergentes para '{c.clave}'. Dataset: "
                             f"{c.peso_min_kg}–{c.peso_max_kg} kg | Tarifario: {rango[0]}–{rango[1]} kg")
    if "peso_max_kg" in t and float(t["peso_max_kg"]) != CLASES_TAMANO[-1].peso_max_kg:
        problemas.append(f"Peso máximo divergente. Dataset: {CLASES_TAMANO[-1].peso_max_kg} | "
                         f"Tarifario: {t['peso_max_kg']}")

    # 2. Grupo de manto
    grupos = _claves_sin_metadatos(t["grupos_manto"])
    if grupos != set(CLAVES_GRUPO):
        problemas.append(f"Grupos de manto divergentes. Dataset: {sorted(CLAVES_GRUPO)} | "
                         f"Tarifario: {sorted(grupos)}")

    # 3. Estado del pelo (sin el caso que decide la propietaria)
    estados = _claves_sin_metadatos(t["recargo_estado_manto"]) - {ESTADO_FUERA_DEL_CLASIFICADOR}
    if estados != set(CLAVES_ESTADO):
        problemas.append(f"Estados del pelo divergentes. Dataset: {sorted(CLAVES_ESTADO)} | "
                         f"Tarifario: {sorted(estados)}")

    # 4. Las razas del tarifario solo pueden usar grupos y tamaños conocidos
    for nombre, raza in (t.get("razas") or {}).items():
        if not isinstance(raza, dict):
            continue
        if raza.get("grupo") not in (None, *CLAVES_GRUPO):
            problemas.append(f"Raza '{nombre}' del tarifario con grupo desconocido: {raza['grupo']}")
        if raza.get("tamano") not in (None, *CLAVES_TAMANO):
            problemas.append(f"Raza '{nombre}' del tarifario con tamaño desconocido: {raza['tamano']}")
    return problemas


def normalizar_estado(valor: str) -> tuple[str, str]:
    """
    Lleva una etiqueta de estado escrita a mano a la clave del clasificador.

    Devuelve (clave, observacion). Acepta los sinónimos que ya usa el tarifario
    (`equivalencias.estado`) y trata `no_recuperable` como `severo`, dejando
    constancia en la observación.
    """
    v = (valor or "").strip().lower().replace("_", " ")
    if not v:
        return "", ""
    if v.replace(" ", "_") in CLAVES_ESTADO:
        return v.replace(" ", "_"), ""
    if v.replace(" ", "_") == ESTADO_FUERA_DEL_CLASIFICADOR:
        return "severo", "estado no_recuperable (se rapa): etiquetado como severo"
    sinonimos = {
        "sin nudos": "sin_motas", "bien": "sin_motas", "normal": "sin_motas",
        "leve": "moderado", "pocos nudos": "moderado", "nudos": "moderado", "motas": "moderado",
        "enredado": "severo", "muchos nudos": "severo", "apelmazado": "severo",
    }
    if v in sinonimos:
        return sinonimos[v], ""
    raise ValueError(f"Estado del pelo desconocido: {valor!r} (use {', '.join(CLAVES_ESTADO)})")


def resumen() -> dict:
    return {
        "tamano": [asdict(c) for c in CLASES_TAMANO],
        "grupo": [asdict(c) for c in CLASES_GRUPO],
        "estado": [asdict(c) for c in CLASES_ESTADO],
    }


if __name__ == "__main__":
    print(json.dumps(resumen(), ensure_ascii=False, indent=2))
    for p in verificar_contra_tarifario():
        print("AVISO:", p)
