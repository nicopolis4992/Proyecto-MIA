"""
Validacion de horarios y propuesta de alternativas.

Combina tres restricciones:
1. Horario laboral y turnos de 2 horas (config_agenda.json: la propietaria
   agenda a las 08:00, 10:00, 12:00, 14:00 y 16:00).
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


def turnos(cfg: dict, dia: str | None = None) -> list[time]:
    """Horas en que puede empezar una cita (vacio = cualquier hora del horario).
    Con `dia`, solo los turnos que caen dentro del horario de ese dia."""
    todos = [time.fromisoformat(t) for t in cfg.get("turnos") or []]
    if dia is None:
        return todos
    if dia in (cfg.get("turnos_por_dia") or {}):
        return [time.fromisoformat(t) for t in cfg["turnos_por_dia"][dia]]
    franja = cfg["horario_laboral"].get(dia)
    if not franja:
        return []
    abre, cierra = time.fromisoformat(franja[0]), time.fromisoformat(franja[1])
    return [t for t in todos if abre <= t < cierra]


def _lista(cosas: list[str], y: str = "y") -> str:
    return ", ".join(cosas[:-1]) + f" {y} " + cosas[-1] if len(cosas) > 1 else "".join(cosas)


def texto_turnos(cfg: dict, dia: str | None = None) -> str:
    return _lista([t.strftime("%H:%M") for t in turnos(cfg, dia)])


NOMBRE_DIA = {"lunes": "lunes", "martes": "martes", "miercoles": "miércoles", "jueves": "jueves",
              "viernes": "viernes", "sabado": "sábado", "domingo": "domingo"}


def texto_turnos_por_dia(cfg: dict) -> str:
    """"lunes, miércoles y viernes a las 12:00, 14:00 y 16:00; martes, ... a las 08:00, ..." """
    grupos: dict[str, list[str]] = {}
    for dia in DIAS:
        horas = texto_turnos(cfg, dia)
        if horas:
            grupos.setdefault(horas, []).append(NOMBRE_DIA[dia])
    if len(grupos) == 1:
        [(horas, dias)] = grupos.items()
        cuando = "todos los días" if len(dias) == 7 else _lista(dias)
        return f"{cuando} a las {horas}"
    return "; ".join(f"{_lista(dias)} a las {horas}" for horas, dias in grupos.items())


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
    del_dia = turnos(cfg, DIAS[inicio.weekday()])
    if turnos(cfg) and del_dia and inicio.time().replace(second=0, microsecond=0) not in del_dia:
        return False, f"ese día las citas son a las {texto_turnos(cfg, DIAS[inicio.weekday()])}"
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
                          franja: str | None = None, hora_minima: time | None = None,
                          max_dias: int | None = None) -> list[datetime]:
    """
    Horarios validos a partir del dia de `desde`, priorizando ese mismo dia.

    Con turnos se ofrecen todos los libres del dia (hasta num_alternativas),
    de los primeros `max_dias` dias que tengan espacio (por defecto
    dias_alternativas de la configuracion). `franja` ("manana" o "tarde") y
    `hora_minima` ("despues de las 3") respetan lo que pidio.
    """
    max_dias = max_dias or cfg.get("dias_alternativas")
    dias_con_espacio = 0
    paso = timedelta(minutes=cfg["paso_alternativas_min"])
    n = cfg["num_alternativas"]
    desde_franja, hasta_franja = FRANJAS.get(franja, (time(0, 0), time(23, 59)))
    elegidos: list[datetime] = []
    dia = desde.replace(hour=0, minute=0, second=0, microsecond=0)
    for _ in range(dias_busqueda):
        horario = cfg["horario_laboral"].get(DIAS[dia.weekday()])
        if horario:
            if turnos(cfg):
                candidatos = [dia.replace(hour=h.hour, minute=h.minute) for h in turnos(cfg, DIAS[dia.weekday()])]
            else:
                apertura = time.fromisoformat(horario[0])
                t = dia.replace(hour=apertura.hour, minute=apertura.minute)
                candidatos = []
                while t.date() == dia.date():
                    candidatos.append(t)
                    t += paso
            del_dia = []
            for t in candidatos:
                en_franja = desde_franja <= t.time() < hasta_franja and (hora_minima is None or t.time() >= hora_minima)
                if t != desde and en_franja and validar_horario(t, duracion_min, modalidad, cotizador, cfg,
                                                               ocupado, ahora)[0]:
                    del_dia.append(t)
            elegidos += _repartir(del_dia, n - len(elegidos))
            dias_con_espacio += bool(del_dia)
            if len(elegidos) >= n or (max_dias and dias_con_espacio >= max_dias):
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
        # Una cita aprobada que espera el "si" del cliente tambien guarda su horario.
        for estado in ("aprobada", "confirmada", "propuesta_cliente"):
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
