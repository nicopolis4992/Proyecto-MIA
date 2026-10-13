"""
SCRUM-95/96 — Línea base del proceso ACTUAL, medida en el historial de WhatsApp.

El proyecto compara el asistente contra cómo se atiende hoy. Este script lee
los exports crudos de WhatsApp Business (un .txt por chat, "sin archivos
multimedia") y calcula, SOLO COMO CIFRAS AGREGADAS:

1. Tiempo de primera respuesta: desde que un cliente escribe (tras un
   silencio) hasta que la propietaria le contesta.
2. Tiempo hasta confirmar una cita: desde el primer mensaje que pide una cita
   hasta el mensaje de la propietaria que la confirma ("listo, le agendo...").
3. Variación de precio: hilos en los que la propietaria dijo dos montos
   distintos en pocos días (cotizado frente a final). Es una señal indicativa:
   un monto puede ser de otro servicio. Se revisa a mano.

Privacidad (LOPDP): los exports crudos viven en datos_crudos/ (excluida del
repo). La salida versionable (resultados/) no contiene nombres, números ni
textos. El archivo de revisión, con fragmentos de mensajes, se escribe junto
a los exports, también fuera del repo.

El anonimizador de SCRUM-63 conserva la fecha pero no la hora, así que estos
tiempos solo se pueden medir aquí, sobre el export crudo.

    python -m evaluacion.linea_base.linea_base_whatsapp \
        --exports datos_crudos/chats --propietaria "Lina"
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

DIR = Path(__file__).parent

# Mismos formatos que datasets/nlu/anonimizador.py (Android e iOS).
LINEA_ANDROID = re.compile(
    r"^(?P<fecha>\d{1,2}/\d{1,2}/\d{2,4}),?\s+(?P<hora>\d{1,2}:\d{2}(?::\d{2})?\s*(?:[ap]\.?\s?m\.?)?)\s*-\s*"
    r"(?P<autor>[^:]{1,60}):\s(?P<texto>.*)$", re.IGNORECASE)
LINEA_IOS = re.compile(
    r"^\[(?P<fecha>\d{1,2}/\d{1,2}/\d{2,4}),?\s+(?P<hora>\d{1,2}:\d{2}(?::\d{2})?\s*(?:[ap]\.?\s?m\.?)?)\]\s*"
    r"(?P<autor>[^:]{1,60}):\s(?P<texto>.*)$", re.IGNORECASE)

# Un cliente "abre" un turno si escribe tras este silencio (o tras un mensaje de ella).
SILENCIO_NUEVO_TURNO = timedelta(hours=4)
# Una confirmación cuenta si llega dentro de este plazo desde el pedido.
PLAZO_CONFIRMACION = timedelta(hours=72)
PLAZO_PRECIO = timedelta(days=7)

# Se aplican sobre el texto sin tildes (ñ -> n).
PIDE_CITA = re.compile(
    r"\b(agend\w*|turno|cita|espacio|disponib\w*|atender\w*|llevar(?:la|lo)?|ban\w* (?:a|para) mi|"
    r"pued\w+ (?:el|la|hoy|manana|lunes|martes|miercoles|jueves|viernes|sabado|domingo))\b")
CONFIRMA = re.compile(
    r"\b(le agendo|la agendo|lo agendo|agendad[oa]|queda (?:agendad|confirmad|separad)\w*|"
    r"le espero|la espero|lo espero|listo,? (?:entonces|le|a las|para)|confirmad[oa]|separad[oa])\b")
MONTO = re.compile(r"(?:\$\s*(\d{1,3}(?:[.,]\d{1,2})?)|(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:\$|usd|d[oó]lares|dolares))")


@dataclass
class Mensaje:
    momento: datetime
    de_propietaria: bool
    texto: str


def _sin_tildes(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _momento(fecha: str, hora: str, dia_primero: bool) -> datetime | None:
    hora = hora.lower().replace(".", "").replace(" ", "")
    pm, am = hora.endswith("pm"), hora.endswith("am")
    hora = hora.rstrip("apm")
    partes_f = [int(x) for x in fecha.split("/")]
    d, m, a = (partes_f if dia_primero else (partes_f[1], partes_f[0], partes_f[2]))
    a = a + 2000 if a < 100 else a
    h, mi, *s = (int(x) for x in hora.split(":"))
    if pm and h < 12:
        h += 12
    if am and h == 12:
        h = 0
    try:
        return datetime(a, m, d, h, mi, s[0] if s else 0)
    except ValueError:
        return None


def leer_export(ruta: Path, propietaria: str, dia_primero: bool = True) -> list[Mensaje]:
    """Mensajes de un chat, con fecha y hora. Las líneas de continuación se unen al anterior."""
    mensajes: list[Mensaje] = []
    for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
        linea = linea.replace("‎", "").replace(" ", " ")
        m = LINEA_ANDROID.match(linea) or LINEA_IOS.match(linea)
        if m:
            momento = _momento(m["fecha"], m["hora"], dia_primero)
            if momento is None:
                continue
            autor = m["autor"].strip()
            mensajes.append(Mensaje(momento, propietaria.lower() in autor.lower(), m["texto"]))
        elif mensajes and linea.strip():
            mensajes[-1].texto += " " + linea.strip()
    return mensajes


def _resumen(minutos: list[float]) -> dict:
    if not minutos:
        return {"n": 0}
    xs = sorted(minutos)
    pct = lambda p: round(xs[min(len(xs) - 1, int(p * len(xs)))], 1)
    return {"n": len(xs), "mediana_min": round(statistics.median(xs), 1), "media_min": round(statistics.mean(xs), 1),
            "p75_min": pct(0.75), "p90_min": pct(0.90)}


def analizar_chat(mensajes: list[Mensaje]) -> dict:
    """Tiempos y hallazgos de un chat. Devuelve también fragmentos para revisión manual."""
    respuestas, confirmaciones, variaciones, revision = [], [], [], []

    # 1. Primera respuesta a cada turno del cliente
    abierto: datetime | None = None
    previo: Mensaje | None = None
    for msg in mensajes:
        if not msg.de_propietaria:
            nuevo_turno = previo is None or previo.de_propietaria or msg.momento - previo.momento > SILENCIO_NUEVO_TURNO
            if abierto is None and nuevo_turno:
                abierto = msg.momento
        elif abierto is not None:
            respuestas.append((msg.momento - abierto).total_seconds() / 60)
            abierto = None
        previo = msg

    # 2. Pedido de cita -> confirmación de la propietaria
    i = 0
    while i < len(mensajes):
        msg = mensajes[i]
        if not msg.de_propietaria and PIDE_CITA.search(_sin_tildes(msg.texto)):
            for j in range(i + 1, len(mensajes)):
                otro = mensajes[j]
                if otro.momento - msg.momento > PLAZO_CONFIRMACION:
                    break
                if otro.de_propietaria and CONFIRMA.search(_sin_tildes(otro.texto)):
                    minutos = (otro.momento - msg.momento).total_seconds() / 60
                    confirmaciones.append(minutos)
                    revision.append({"tipo": "confirmacion", "minutos": round(minutos, 1),
                                     "pedido": msg.texto[:120], "confirmacion": otro.texto[:120]})
                    i = j
                    break
        i += 1

    # 3. Dos montos distintos de la propietaria en pocos días
    montos = [(m.momento, float((g.group(1) or g.group(2)).replace(",", ".")), m.texto)
              for m in mensajes if m.de_propietaria for g in MONTO.finditer(_sin_tildes(m.texto))]
    for (t1, v1, x1), (t2, v2, x2) in zip(montos, montos[1:]):
        if v1 != v2 and t2 - t1 <= PLAZO_PRECIO and 3 <= v1 <= 120 and 3 <= v2 <= 120:
            variaciones.append(abs(v2 - v1))
            revision.append({"tipo": "precio", "diferencia": abs(v2 - v1), "antes": x1[:120], "despues": x2[:120]})
    return {"respuestas": respuestas, "confirmaciones": confirmaciones, "variaciones": variaciones,
            "revision": revision}


def analizar(rutas: list[Path], propietaria: str, dia_primero: bool = True) -> tuple[dict, list[dict]]:
    total = {"respuestas": [], "confirmaciones": [], "variaciones": []}
    revision, mensajes_total, chats_con_ella = [], 0, 0
    for ruta in rutas:
        mensajes = leer_export(ruta, propietaria, dia_primero)
        mensajes_total += len(mensajes)
        if not any(m.de_propietaria for m in mensajes):
            continue  # el nombre de la propietaria no coincide en este chat
        chats_con_ella += 1
        r = analizar_chat(mensajes)
        for k in total:
            total[k] += r[k]
        revision += [{"chat": ruta.name, **x} for x in r["revision"]]

    en_horario = [m for m in total["respuestas"] if m <= 12 * 60]  # descarta respuestas al día siguiente
    resultado = {
        "chats": len(rutas), "chats_con_propietaria": chats_con_ella, "mensajes": mensajes_total,
        "primera_respuesta": _resumen(total["respuestas"]),
        "primera_respuesta_mismo_dia": _resumen(en_horario),
        "tiempo_hasta_confirmar": _resumen(total["confirmaciones"]),
        "variacion_precio_usd": ({"n": len(total["variaciones"]),
                                  "mediana": round(statistics.median(total["variaciones"]), 2),
                                  "media": round(statistics.mean(total["variaciones"]), 2)}
                                 if total["variaciones"] else {"n": 0}),
        "advertencia": ("Detección por reglas: revisar a mano el archivo de revisión antes de reportar. "
                        "La variación de precio es indicativa (un segundo monto puede ser otro servicio)."),
    }
    return resultado, revision


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exports", type=Path, required=True, help="carpeta con los .txt (o un solo .txt)")
    ap.add_argument("--propietaria", required=True, help="nombre (o parte) con el que aparece ella en el export")
    ap.add_argument("--mes-primero", action="store_true", help="fechas mm/dd/aa (por defecto dd/mm/aa)")
    args = ap.parse_args()

    rutas = sorted(args.exports.glob("*.txt")) if args.exports.is_dir() else [args.exports]
    resultado, revision = analizar(rutas, args.propietaria, not args.mes_primero)

    salida = DIR / "resultados"
    salida.mkdir(exist_ok=True)
    (salida / "linea_base.json").write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")
    carpeta_cruda = args.exports if args.exports.is_dir() else args.exports.parent
    ruta_rev = carpeta_cruda / "revision_linea_base.json"  # fuera del repo: contiene fragmentos de mensajes
    ruta_rev.write_text(json.dumps(revision, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    print(f"\nRevisar a mano: {ruta_rev}  (NO subir al repo)")


if __name__ == "__main__":
    main()
