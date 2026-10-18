"""
SCRUM-95/96 — Validación del tarifario v2 contra lo que la propietaria cobró de verdad.

Fuente: su registro de cuentas en Excel (una hoja por mes, sept-2024 a la
fecha), con el monto cobrado, la raza y un código de servicio en
"Observaciones" (tabla de siglas del mismo Excel):
    SC servicio completo · SB solo baño · SBas servicio básico · SP servicio premium
    BA baño antipulgas · BM baño medicado · BB baño blanqueador

Para cada servicio cobrado con raza y código de catálogo, se cotiza con el
motor (tarifario_v2.json) lo mismo que sabría el bot por texto: raza y
servicio, sin saber el estado del pelo. Se compara:
- si lo cobrado cae dentro del rango que da el motor;
- la diferencia contra el precio sin nudos (lo cobrado menos el motor);
- por raza, para ver qué celdas del tarifario están altas o bajas.

Se excluyen los servicios con extras (tinte, antipulgas cobrado, blanqueador,
hospedaje) y, aparte, los que incluyen puerta a puerta (el monto puede traer
el traslado sumado).

Privacidad: el Excel vive fuera del repo (datos_crudos/ o READ/). La salida
versionable solo tiene cifras agregadas y razas; no nombres de mascotas.

    python -m evaluacion.tarifario.validar_con_excel --excel "datos_crudos/Cuentas peluqueria.xlsx"
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import unicodedata
from collections import defaultdict
from pathlib import Path

from app.config import RUTA_TARIFARIO
from app.cotizacion.motor_cotizacion_v2 import Tarifario, cotizar_mascota

DIR = Path(__file__).parent
SALIDA = DIR / "resultados"

_EXTRAS = re.compile(r"tinte|blanque|hospedaje|corte de cola|shampoo especial")
_ANTIPULGAS_COBRADO = re.compile(r"antipulga(?!s? gratis)")
_DOMICILIO = re.compile(r"domicilio|adom\b|puerta a puerta|retiro")


def _sin_tildes(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t).lower())
    return "".join(c for c in t if not unicodedata.combining(c)).strip()


def servicio_de(observacion: str) -> tuple[str | None, str]:
    """(servicio del catálogo o None, motivo) a partir de la columna Observaciones."""
    o = _sin_tildes(observacion)
    if not o:
        return None, "sin_codigo"
    if _EXTRAS.search(o) or _ANTIPULGAS_COBRADO.search(o):
        return None, "con_extras"
    codigo = re.match(r"(sbas|sbm|sc|sb|sp|ba|bm|bb)\b", o)
    if codigo:
        servicio = {"sc": "completo", "sb": "express", "sbas": "basico", "sp": "premium"}.get(codigo.group(1))
        return (servicio, "ok") if servicio else (None, "bano_especial")
    if o.startswith(("solo bano", "bano")):
        return "express", "ok"
    if o.startswith("peluqueria"):
        return "completo", "ok"
    return None, "sin_codigo"


def leer_excel(ruta: Path) -> list[dict]:
    """Filas con monto cobrado. No se conserva el nombre de la mascota."""
    from python_calamine import CalamineWorkbook

    wb = CalamineWorkbook.from_path(str(ruta))
    filas = []
    for hoja in wb.sheet_names:
        datos = wb.get_sheet_by_name(hoja).to_python()
        cab = next((i for i, r in enumerate(datos) if r and str(r[0]).strip() == "Nro"), None)
        if cab is None:
            continue
        nombres = [_sin_tildes(c) for c in datos[cab]]
        for r in datos[cab + 1:]:
            d = dict(zip(nombres, r))
            monto = d.get("ingresos")
            if not isinstance(monto, (int, float)) or monto <= 0:
                continue
            filas.append({"mes": hoja.strip(), "anio": hoja.strip()[-4:], "cobrado": float(monto),
                          "origen": str(d.get("origen", "")).strip(), "observacion": str(d.get("observaciones", "")),
                          "raza": str(d.get("raza", "")).strip()})
    return filas


def _resumen(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "media": round(statistics.mean(xs), 2), "mediana": round(statistics.median(xs), 2),
            "media_abs": round(statistics.mean(abs(x) for x in xs), 2)}


def validar(filas: list[dict], t: Tarifario) -> dict:
    excluidos: dict[str, int] = defaultdict(int)
    casos = []
    for f in filas:
        servicio, motivo = servicio_de(f["observacion"])
        if servicio is None:
            excluidos[motivo] += 1
            continue
        if not f["raza"]:
            excluidos["sin_raza"] += 1
            continue
        razas, avisos = t.resolver_razas(f["raza"])
        if not razas or any(clave is None for clave, _ in razas):
            excluidos["raza_no_reconocida"] += 1
            continue
        m = {"raza": f["raza"], "servicio": servicio, "comportamiento": "tranquilo"}
        r = cotizar_mascota(t, dict(m))
        base = cotizar_mascota(t, {**m, "estado": "sin_motas"})
        if r.get("rechazada") or not r.get("rango") or not base.get("rango"):
            excluidos["no_cotizable"] += 1
            continue
        lo, hi = r["rango"]
        b_lo, b_hi = base["rango"]
        determinada = b_lo == b_hi  # la raza basta para fijar tamaño y pelo
        casos.append({
            "anio": f["anio"], "servicio": servicio, "raza": " x ".join(c for c, _ in razas),
            "domicilio": bool(_DOMICILIO.search(_sin_tildes(f["observacion"]))),
            "cobrado": f["cobrado"], "rango": [lo, hi], "base": [b_lo, b_hi], "determinada": determinada,
            "dentro": lo <= f["cobrado"] <= hi,
            # Contra el precio sin nudos; si la raza no fija el tamaño, contra el punto medio.
            "diferencia": round(f["cobrado"] - (b_lo + b_hi) / 2, 2),
        })

    def bloque(cs: list[dict]) -> dict:
        return {"n": len(cs),
                "dentro_del_rango_pct": round(100 * sum(c["dentro"] for c in cs) / len(cs), 1) if cs else None,
                "cobrado_menos_motor_sin_nudos": _resumen([c["diferencia"] for c in cs])}

    salon = [c for c in casos if not c["domicilio"]]
    por_raza = defaultdict(list)
    for c in salon:
        if c["determinada"] and c["servicio"] == "completo":
            por_raza[c["raza"]].append(c)
    tabla_razas = sorted((
        {"raza": raza, "n": len(cs), "cobrado_mediana": statistics.median(c["cobrado"] for c in cs),
         "cobrado_min": min(c["cobrado"] for c in cs), "cobrado_max": max(c["cobrado"] for c in cs),
         "motor_sin_nudos": cs[0]["base"][0], "motor_rango": cs[0]["rango"],
         "dentro_del_rango_pct": round(100 * sum(c["dentro"] for c in cs) / len(cs), 1)}
        for raza, cs in por_raza.items() if len(cs) >= 3), key=lambda x: -x["n"])

    return {
        "fuente": "registro de cuentas de la propietaria (Excel), servicios con raza y código de catálogo",
        "version_tarifario": t.datos.get("version"),
        "registros_leidos": len(filas),
        "excluidos": dict(excluidos),
        "en_salon": bloque(salon),
        "en_salon_raza_determinada": bloque([c for c in salon if c["determinada"]]),
        "en_salon_por_servicio": {s: bloque([c for c in salon if c["servicio"] == s])
                                  for s in sorted({c["servicio"] for c in salon})},
        "en_salon_por_anio": {a: bloque([c for c in salon if c["anio"] == a]) for a in sorted({c["anio"] for c in salon})},
        "con_puerta_a_puerta": bloque([c for c in casos if c["domicilio"]]),
        "completo_por_raza": tabla_razas,
        "lectura": ("dentro_del_rango: lo cobrado cae en el rango que el bot daria sabiendo raza y servicio (sin "
                    "saber nudos). cobrado_menos_motor_sin_nudos > 0: ella cobra mas que el precio sin nudos del "
                    "motor (puede ser por nudos, que el Excel no registra)."),
    }


def markdown(r: dict) -> str:
    def fila(nombre: str, b: dict) -> str:
        d = b["cobrado_menos_motor_sin_nudos"]
        return (f"| {nombre} | {b['n']} | {b['dentro_del_rango_pct']} % | {d.get('media', '-')} | "
                f"{d.get('mediana', '-')} | {d.get('media_abs', '-')} |")

    lineas = [f"# Tarifario v{r['version_tarifario']} frente a lo cobrado (Excel de la propietaria)", "",
              f"Registros con monto: {r['registros_leidos']}. Excluidos: "
              + ", ".join(f"{k} {v}" for k, v in sorted(r["excluidos"].items())) + ".", "",
              "| Grupo | n | Dentro del rango | Dif. media (USD) | Dif. mediana | Error abs. medio |",
              "|---|---|---|---|---|---|",
              fila("En el salón", r["en_salon"]),
              fila("En el salón, raza que fija tamaño y pelo", r["en_salon_raza_determinada"])]
    lineas += [fila(f"Servicio: {s}", b) for s, b in r["en_salon_por_servicio"].items()]
    lineas += [fila(f"Año {a}", b) for a, b in r["en_salon_por_anio"].items()]
    lineas += [fila("Con puerta a puerta (monto con traslado)", r["con_puerta_a_puerta"]), "",
               "## Baño Completo por raza (en el salón, 3 o más servicios)", "",
               "| Raza | n | Cobrado (mediana) | Cobrado (mín–máx) | Motor sin nudos | Rango del motor | Dentro |",
               "|---|---|---|---|---|---|---|"]
    lineas += [f"| {x['raza']} | {x['n']} | {x['cobrado_mediana']:g} | {x['cobrado_min']:g}–{x['cobrado_max']:g} | "
               f"{x['motor_sin_nudos']:g} | {x['motor_rango'][0]:g}–{x['motor_rango'][1]:g} | {x['dentro_del_rango_pct']} % |"
               for x in r["completo_por_raza"]]
    lineas += ["", r["lectura"]]
    return "\n".join(lineas) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--excel", type=Path, required=True)
    args = ap.parse_args()
    r = validar(leer_excel(args.excel), Tarifario.desde_archivo(RUTA_TARIFARIO))
    SALIDA.mkdir(exist_ok=True)
    (SALIDA / "validacion_excel.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    (SALIDA / "validacion_excel.md").write_text(markdown(r), encoding="utf-8")
    print(markdown(r))


if __name__ == "__main__":
    main()
