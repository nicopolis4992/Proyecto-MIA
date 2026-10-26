"""
Interpretabilidad del motor de cotización (Figura 8 del informe, sección 7.4).

Sobre todos los escenarios del tarifario (servicio x tamaño x grupo de manto x
estado del pelo x comportamiento):

(a) Influencia sobre el precio: valor de Shapley exacto de cada atributo sobre el
    precio de cada escenario (función de valor: precio esperado fijando los
    atributos del subconjunto y promediando los demás con fondo uniforme); se
    reporta el |Shapley| medio.
(b) Valor de información: reparto de Shapley de la reducción de la semiamplitud
    del rango que da el motor al declarar cada atributo (el servicio siempre se
    conoce), partiendo de la semiamplitud media sin datos.

Describe las reglas del tarifario, construidas por el equipo con los precios de
la propietaria; no son datos de cobros reales.

    python -m evaluacion.tarifario.interpretabilidad_motor [--tarifario ruta.json]
"""

from __future__ import annotations

import argparse
import itertools
import json
import statistics
import sys
from math import factorial
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
SALIDA = Path(__file__).parent / "resultados" / "interpretabilidad_motor.json"


def _shapley(jugadores, valor):
    n = len(jugadores)
    phi = {}
    for i in jugadores:
        otros = [j for j in jugadores if j != i]
        total = 0.0
        for r in range(n):
            for s in itertools.combinations(otros, r):
                peso = factorial(len(s)) * factorial(n - len(s) - 1) / factorial(n)
                total += peso * (valor(set(s) | {i}) - valor(set(s)))
        phi[i] = total
    return phi


def analizar(ruta: Path) -> dict:
    from app.cotizacion.motor_cotizacion_v2 import (COMPORTAMIENTOS_COTIZABLES, ESTADOS_COTIZABLES, GRUPOS,
                                                    SERVICIOS_CATALOGO, TAMANOS, Tarifario, cotizar_mascota,
                                                    precio_escenario)

    t = Tarifario(json.loads(Path(ruta).read_text(encoding="utf-8")))
    dims = {"servicio": SERVICIOS_CATALOGO, "tamano": TAMANOS, "grupo": GRUPOS, "estado": ESTADOS_COTIZABLES,
            "comportamiento": COMPORTAMIENTOS_COTIZABLES}
    nombres = list(dims)
    escenarios = list(itertools.product(*dims.values()))

    def precio(x):
        lo, hi, _ = precio_escenario(t, *x)
        return (lo + hi) / 2

    cache: dict = {}

    def esperado(x, fijos):
        clave = tuple(x[i] if i in fijos else None for i in range(5))
        if clave not in cache:
            libres = [[x[i]] if i in fijos else dims[nombres[i]] for i in range(5)]
            cache[clave] = statistics.mean(precio(z) for z in itertools.product(*libres))
        return cache[clave]

    abs_phi = {k: [] for k in nombres}
    efecto_tamano: dict = {}
    for x in escenarios:
        phi = _shapley(list(range(5)), lambda s, x=x: esperado(x, s))
        for i, v in phi.items():
            abs_phi[nombres[i]].append(abs(v))
        efecto_tamano.setdefault(x[1], []).append(phi[1])

    def semi(m):
        r = cotizar_mascota(t, dict(m))
        return (r["rango"][1] - r["rango"][0]) / 2

    atributos = ["tamano", "grupo", "estado", "comportamiento"]
    cache_semi: dict = {}

    def semi_media(s):
        clave = tuple(sorted(s))
        if clave not in cache_semi:
            cache_semi[clave] = statistics.mean(
                semi({"servicio": sv, **dict(zip(clave, vs))})
                for sv in SERVICIOS_CATALOGO for vs in itertools.product(*(dims[k] for k in clave)))
        return cache_semi[clave]

    reparto = _shapley(atributos, lambda s: -semi_media(s))
    return {
        "version_tarifario": t.datos.get("version"),
        "escenarios": len(escenarios),
        "shapley_abs_medio_usd": {k: round(statistics.mean(v), 2) for k, v in abs_phi.items()},
        "efecto_medio_por_tamano_usd": {k: round(statistics.mean(v), 2) for k, v in efecto_tamano.items()},
        "semiamplitud_sin_datos_usd": round(semi_media([]), 2),
        "semiamplitud_tamano_y_grupo_usd": round(semi_media(["tamano", "grupo"]), 2),
        "semiamplitud_tamano_grupo_estado_usd": round(semi_media(["tamano", "grupo", "estado"]), 2),
        "semiamplitud_todo_declarado_usd": round(semi_media(atributos), 2),
        "valor_informacion_usd": {k: round(v, 2) for k, v in reparto.items()},
    }


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tarifario", type=Path, default=RAIZ / "app" / "cotizacion" / "tarifario_v2.json")
    args = ap.parse_args()
    r = analizar(args.tarifario)
    SALIDA.parent.mkdir(exist_ok=True)
    SALIDA.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
