"""
SCRUM-101 — Reporte de cobertura y cálculo del volumen mínimo exigible.

Este módulo responde a la pregunta que la historia debe dejar contestada antes
de que SCRUM-102 empiece a entrenar: ¿cuántas fotografías reales faltan, de qué
clases, para que la métrica de SCRUM-105 signifique algo?

CÁLCULO DEL MÍNIMO POR CLASE
----------------------------
SCRUM-105 compromete F1 macro >= 0,85. Una métrica sin intervalo de confianza no
es un resultado: es una anécdota. Para una proporción p en torno a 0,85, la
semiamplitud del intervalo de Wald al 95 % es 1,96 * raíz(p(1-p)/n). Despejando
n para una semiamplitud objetivo se obtiene el tamaño mínimo del conjunto de
prueba POR CLASE. El módulo lo calcula en vez de fijarlo a dedo, para que la
cifra sea trazable, que es el criterio que ya se aplicó en SCRUM-63 al rechazar
el test de 56 casos como estimación estable.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict

from clases import CLASES_PELAJE, CLASES_TAMANO
from dataset import FUENTES_DOMINIO_REAL, PROPORCIONES_REAL, Registro

Z_95 = 1.959963984540054


def n_minimo_por_clase(p_esperada: float = 0.85, semiamplitud: float = 0.10) -> int:
    """Tamaño mínimo del conjunto de prueba por clase, en imágenes."""
    if not 0 < p_esperada < 1:
        raise ValueError("p_esperada debe estar en (0,1).")
    if not 0 < semiamplitud < 1:
        raise ValueError("semiamplitud debe estar en (0,1).")
    return math.ceil((Z_95 ** 2) * p_esperada * (1 - p_esperada) / (semiamplitud ** 2))


def semiamplitud_para(n: int, p_esperada: float = 0.85) -> float:
    """Intervalo que realmente se obtiene con n casos. Útil para reportar honestamente."""
    if n <= 0:
        return float("nan")
    return Z_95 * math.sqrt(p_esperada * (1 - p_esperada) / n)


def cobertura(registros: list[Registro]) -> dict:
    """Conteos por clase, dimensión, partición y fuente."""
    reales = [r for r in registros if r.fuente in FUENTES_DOMINIO_REAL]
    salida: dict = {
        "total": len(registros),
        "total_dominio_real": len(reales),
        "por_fuente": dict(Counter(r.fuente for r in registros)),
        "por_particion": dict(Counter(r.particion for r in registros)),
        "mascotas_distintas": len({r.mascota_id for r in reales}),
        "con_referencia_escala": sum(1 for r in reales if r.escala_presente),
        "dimensiones": {},
    }

    for nombre, clases, atributo in (
        ("tamano", CLASES_TAMANO, "tamano"),
        ("pelaje", CLASES_PELAJE, "pelaje"),
    ):
        detalle: dict[str, dict] = {}
        for c in clases:
            en_test = sum(1 for r in reales if r.particion == "test" and getattr(r, atributo) == c.clave)
            en_real = sum(1 for r in reales if getattr(r, atributo) == c.clave)
            en_total = sum(1 for r in registros if getattr(r, atributo) == c.clave)
            detalle[c.clave] = {
                "etiqueta": c.etiqueta,
                "total_todas_las_fuentes": en_total,
                "dominio_real": en_real,
                "en_test": en_test,
            }
        salida["dimensiones"][nombre] = detalle

    return salida


def brecha(registros: list[Registro], semiamplitud: float = 0.10) -> dict:
    """
    Cuántas fotografías reales faltan, por clase, para cerrar la historia.

    Devuelve tanto el faltante en el conjunto de prueba como el faltante total
    de captura, porque el conjunto de prueba es solo una fracción
    (`PROPORCIONES_REAL['test']`) de las fotografías reales que se recojan.
    """
    n_min = n_minimo_por_clase(semiamplitud=semiamplitud)
    cob = cobertura(registros)
    proporcion_test = PROPORCIONES_REAL["test"]

    resultado: dict = {
        "n_minimo_por_clase_en_test": n_min,
        "semiamplitud_objetivo": semiamplitud,
        "proporcion_test": proporcion_test,
        "detalle": {},
        "captura_total_necesaria": 0,
    }

    faltante_captura_max = 0
    for dimension, clases in cob["dimensiones"].items():
        filas = {}
        for clave, datos in clases.items():
            falta_test = max(0, n_min - datos["en_test"])
            falta_captura = math.ceil(falta_test / proporcion_test) if falta_test else 0
            filas[clave] = {
                "etiqueta": datos["etiqueta"],
                "en_test": datos["en_test"],
                "falta_en_test": falta_test,
                "fotos_reales_a_capturar": falta_captura,
                "ic95_actual": (
                    None if datos["en_test"] == 0
                    else round(semiamplitud_para(datos["en_test"]), 4)
                ),
            }
            faltante_captura_max += falta_captura
        resultado["detalle"][dimension] = filas

    # Una misma fotografía aporta simultáneamente a una clase de tamaño y a una
    # de pelaje. El total necesario lo marca la dimensión más exigente, no la
    # suma de ambas.
    totales_por_dimension = {
        d: sum(f["fotos_reales_a_capturar"] for f in filas.values())
        for d, filas in resultado["detalle"].items()
    }
    resultado["captura_por_dimension"] = totales_por_dimension
    resultado["captura_total_necesaria"] = max(totales_por_dimension.values()) if totales_por_dimension else 0
    return resultado


def cobertura_del_mapeo(filas_mapeo: list[dict]) -> dict:
    """
    Cobertura teórica que aporta Stanford Dogs, medida en RAZAS.

    Es el dato que decide si Stanford Dogs sirve como fuente de preentrenamiento
    para cada clase o si esa clase depende por completo de fotos propias.
    """
    utilizables = [f for f in filas_mapeo if f["uso"] != "excluida"]
    con_tamano = [f for f in utilizables if f["uso"] == "completa"]

    return {
        "razas_totales": len(filas_mapeo),
        "razas_excluidas": len(filas_mapeo) - len(utilizables),
        "razas_con_tamano_utilizable": len(con_tamano),
        "razas_solo_pelaje": len(utilizables) - len(con_tamano),
        "tamano_por_raza": dict(Counter(f["tamano"] for f in con_tamano)),
        "pelaje_por_raza": dict(Counter(f["pelaje"] for f in utilizables)),
        "razas_pelo_duro_sin_categoria": sum(
            1 for f in utilizables if f["pelaje_observacion"] == "duro"
        ),
    }


def imprimir_reporte(cob: dict, brec: dict, cob_mapeo: dict | None = None) -> str:
    """Reporte legible para pegar en el comentario de la historia en Jira."""
    lineas: list[str] = []
    a = lineas.append

    a("=" * 72)
    a("SCRUM-101 — REPORTE DE COBERTURA DEL DATASET DE IMÁGENES")
    a("=" * 72)
    a("")
    a(f"Imágenes en el manifiesto ........ {cob['total']}")
    a(f"  de dominio real (propias) ...... {cob['total_dominio_real']}")
    a(f"  mascotas distintas ............. {cob['mascotas_distintas']}")
    a(f"  con referencia de escala ....... {cob['con_referencia_escala']}")
    a(f"Reparto por partición ............ {cob['por_particion']}")
    a("")

    if cob_mapeo:
        a("-" * 72)
        a("APORTE DE STANFORD DOGS (medido en razas, no en imágenes)")
        a("-" * 72)
        a(f"Razas del dataset ................ {cob_mapeo['razas_totales']}")
        a(f"Excluidas ........................ {cob_mapeo['razas_excluidas']}")
        a(f"Con etiqueta de tamaño utilizable  {cob_mapeo['razas_con_tamano_utilizable']}")
        a(f"Solo utilizables para pelaje ..... {cob_mapeo['razas_solo_pelaje']}")
        a(f"Tamaño por raza .................. {cob_mapeo['tamano_por_raza']}")
        a(f"Pelaje por raza .................. {cob_mapeo['pelaje_por_raza']}")
        a(f"Razas de pelo duro sin categoría . {cob_mapeo['razas_pelo_duro_sin_categoria']}")
        a("")

    a("-" * 72)
    a(f"BRECHA HASTA UNA MÉTRICA DEFENDIBLE (IC 95 % de ±{brec['semiamplitud_objetivo']:.0%})")
    a("-" * 72)
    a(f"Mínimo por clase en el conjunto de prueba: {brec['n_minimo_por_clase_en_test']} imágenes")
    a("")
    for dimension, filas in brec["detalle"].items():
        a(f"  [{dimension}]")
        a(f"  {'clase':<18}{'en test':>9}{'falta':>8}{'a capturar':>13}")
        for clave, f in filas.items():
            a(f"  {f['etiqueta']:<18}{f['en_test']:>9}{f['falta_en_test']:>8}{f['fotos_reales_a_capturar']:>13}")
        a("")
    a(f"Fotografías reales a capturar (dimensión más exigente): {brec['captura_total_necesaria']}")
    a("")
    a("-" * 72)
    a("SENSIBILIDAD: qué exige cada nivel de precisión de la métrica")
    a("-" * 72)
    a(f"  {'IC 95%':>8}{'n por clase':>14}{'test (4 clases)':>18}{'fotos reales':>15}")
    for s in (0.05, 0.10, 0.15, 0.20):
        n = n_minimo_por_clase(semiamplitud=s)
        a(f"  {s:>7.0%}{n:>14}{n * 4:>18}{math.ceil(n * 4 / PROPORCIONES_REAL['test']):>15}")
    a("")
    n_10 = n_minimo_por_clase(semiamplitud=0.10)
    fotos_10 = math.ceil(n_10 * 4 / PROPORCIONES_REAL["test"])
    a(f"  Leer así: comprometer F1 >= 0,85 con un margen de ±10 puntos exige un")
    a(f"  conjunto de prueba de {n_10 * 4} imágenes reales y, por tanto, unas {fotos_10}")
    a("  fotografías propias en total. Con ~12 clientes fijos al mes, esa cifra")
    a("  es la que debe negociarse con la propietaria o, en su defecto,")
    a("  relajarse de forma explícita y documentada en SCRUM-105.")
    a("=" * 72)
    return "\n".join(lineas)
