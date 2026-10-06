"""
Validacion de horarios y propuesta de alternativas.

Combina tres restricciones:
1. Horario laboral (config_agenda.json, provisional).
2. Restriccion vehicular para puerta a puerta (parametrizada en el
   tarifario v2, seccion pico_y_placa; evaluada por el Cotizador).
3. Ocupacion del calendario: PUNTO DE INTEGRACION con SCRUM-72 (Google
   Calendar, Daniel Ocampo). Mientras no exista, `ocupado` solo detecta
   choques con citas aprobadas/confirmadas en la base local.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Callable

RUTA_CONFIG = Path(__file__).parent / "config_agenda.json"
DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


def cargar_config(ruta: Path = RUTA_CONFIG) -> dict:
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def _dentro_de_horario(inicio: datetime, duracion_min: int, cfg: dict) -> bool:
    franja = cfg["horario_laboral"].get(DIAS[inicio.weekday()])
    if not franja:
        return False
    abre, cierra = time.fromisoformat(franja[0]), time.fromisoformat(franja[1])
    fin = inicio + timedelta(minutes=duracion_min)
    return inicio.time() >= abre and fin.time() <= cierra and fin.date() == inicio.date()


def validar_horario(inicio: datetime, duracion_min: int, modalidad: str, cotizador,
                    cfg: dict, ocupado: Callable[[datetime, int], bool] | None = None,
                    ahora: datetime | None = None) -> tuple[bool, str | None]:
    """Devuelve (valido, motivo_legible)."""
    if ahora and inicio < ahora + timedelta(hours=cfg["antelacion_minima_horas"]):
        return False, "ese horario ya pasó o es demasiado pronto"
    # La restriccion vehicular se informa primero: es el motivo que la
    # clienta puede resolver cambiando a modalidad salon.
    if modalidad == "puerta_a_puerta" and cotizador.restringido(inicio):
        return False, ("a esa hora el vehículo tiene restricción de circulación para el retiro "
                       "a domicilio; si prefiere traerlo al salón, puedo revisar ese horario")
    if not _dentro_de_horario(inicio, duracion_min, cfg):
        return False, "está fuera del horario de atención"
    if ocupado and ocupado(inicio, duracion_min):
        return False, "ese horario ya está ocupado"
    return True, None


FRANJAS = {"manana": (time(0, 0), time(12, 0)), "tarde": (time(12, 0), time(23, 59))}


def _repartir(horarios: list[datetime], n: int) -> list[datetime]:
    """Elige n horarios repartidos en el dia (no los n primeros seguidos)."""
    if len(horarios) <= n:
        return horarios
    if n == 1:
        return horarios[:1]
    paso = (len(horarios) - 1) / (n - 1)
    return [horarios[round(i * paso)] for i in range(n)]


def proponer_alternativas(desde: datetime, duracion_min: int, modalidad: str, cotizador,
                          cfg: dict, ocupado: Callable[[datetime, int], bool] | None = None,
                          ahora: datetime | None = None, dias_busqueda: int = 7,
                          franja: str | None = None, hora_minima: time | None = None) -> list[datetime]:
    """
    N horarios validos a partir del dia de `desde`, priorizando ese mismo dia.

    Dentro de un dia se ofrecen horarios repartidos (manana, mediodia, tarde)
    para que el cliente vea todo el rango disponible. `franja` ("manana" o
    "tarde") y `hora_minima` ("despues de las 3") respetan lo que pidio.
    """
    paso = timedelta(minutes=cfg["paso_alternativas_min"])
    n = cfg["num_alternativas"]
    desde_franja, hasta_franja = FRANJAS.get(franja, (time(0, 0), time(23, 59)))
    elegidos: list[datetime] = []
    dia = desde.replace(hour=0, minute=0, second=0, microsecond=0)
    for _ in range(dias_busqueda):
        horario = cfg["horario_laboral"].get(DIAS[dia.weekday()])
        if horario:
            apertura = time.fromisoformat(horario[0])
            t = dia.replace(hour=apertura.hour, minute=apertura.minute)
            del_dia = []
            while t.date() == dia.date():
                en_franja = desde_franja <= t.time() < hasta_franja and (hora_minima is None or t.time() >= hora_minima)
                if t != desde and en_franja and validar_horario(t, duracion_min, modalidad, cotizador, cfg,
                                                               ocupado, ahora)[0]:
                    del_dia.append(t)
                t += paso
            elegidos += _repartir(del_dia, n - len(elegidos))
            if len(elegidos) >= n:
                return elegidos
        dia += timedelta(days=1)
    return elegidos


def ocupado_combinado(repo, calendario=None) -> Callable[[datetime, int], bool]:
    """Ocupado si choca con la base local o con Google Calendar (si esta configurado)."""
    local = ocupado_segun_repositorio(repo)

    def _ocupado(inicio: datetime, duracion_min: int) -> bool:
        if local(inicio, duracion_min):
            return True
        if calendario is not None:
            try:
                return calendario.ocupado(inicio, duracion_min)
            except Exception:  # noqa: BLE001 - sin calendario se sigue con la base local
                return False
        return False
    return _ocupado


def ocupado_segun_repositorio(repo) -> Callable[[datetime, int], bool]:
    """Choque con citas aprobadas/confirmadas en la base local (provisional)."""
    def _ocupado(inicio: datetime, duracion_min: int) -> bool:
        fin = inicio + timedelta(minutes=duracion_min)
        for estado in ("aprobada", "confirmada"):
            for c in repo.citas_por_estado(estado):
                if not c.get("fecha_hora"):
                    continue
                ci = datetime.fromisoformat(c["fecha_hora"])
                if ci.tzinfo is None and inicio.tzinfo is not None:
                    ci = ci.replace(tzinfo=inicio.tzinfo)
                cf = ci + timedelta(minutes=(c.get("cotizacion") or {}).get("duracion_agenda_min", 60))
                if inicio < cf and ci < fin:
                    return True
        return False
    return _ocupado
