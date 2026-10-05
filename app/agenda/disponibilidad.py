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


def proponer_alternativas(desde: datetime, duracion_min: int, modalidad: str, cotizador,
                          cfg: dict, ocupado: Callable[[datetime, int], bool] | None = None,
                          ahora: datetime | None = None, dias_busqueda: int = 7) -> list[datetime]:
    """Primeros N horarios validos a partir de `desde`, priorizando el mismo dia."""
    paso = timedelta(minutes=cfg["paso_alternativas_min"])
    n = cfg["num_alternativas"]
    candidatos: list[datetime] = []
    dia = desde.replace(hour=0, minute=0, second=0, microsecond=0)
    for _ in range(dias_busqueda):
        franja = cfg["horario_laboral"].get(DIAS[dia.weekday()])
        if franja:
            apertura = time.fromisoformat(franja[0])
            t = dia.replace(hour=apertura.hour, minute=apertura.minute)
            while t.date() == dia.date():
                if t != desde and validar_horario(t, duracion_min, modalidad, cotizador, cfg, ocupado, ahora)[0]:
                    candidatos.append(t)
                    if len(candidatos) >= n:
                        return candidatos
                t += paso
        dia += timedelta(days=1)
    return candidatos


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
