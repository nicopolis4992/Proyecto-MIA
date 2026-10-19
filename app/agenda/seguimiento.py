"""
SCRUM-76: seguimiento de las solicitudes que la propietaria no ha respondido.

Corre periodicamente (app/main.py). Para cada cita en `pendiente_aprobacion`:

1. Si la hora de la cita ya esta demasiado cerca (o paso) sin aprobacion, la
   solicitud vence: se trata como un rechazo y al cliente se le ofrecen otros
   horarios, igual que cuando la propietaria dice "no".
2. Si pasaron `recordatorio_min` desde el ultimo aviso, se le recuerda a la
   propietaria (hasta `max_recordatorios` veces), solo dentro de `horas_aviso`
   para no escribirle de madrugada.
3. Agotados los recordatorios, se le avisa UNA vez al cliente que su solicitud
   sigue en revision, para que no quede sin respuesta.

Los tiempos estan en config_agenda.json -> seguimiento_aprobacion.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.agenda import mensajes

logger = logging.getLogger("agenda.seguimiento")

POR_DEFECTO = {"recordatorio_min": 45, "max_recordatorios": 2, "vence_horas_antes": 1,
               "horas_aviso": ["07:00", "21:00"]}


def _config(cfg_agenda: dict) -> dict:
    return {**POR_DEFECTO, **(cfg_agenda.get("seguimiento_aprobacion") or {})}


def _en_horas_de_aviso(momento: datetime, cfg: dict) -> bool:
    desde, hasta = cfg["horas_aviso"]
    return desde <= momento.strftime("%H:%M") < hasta


def revisar(procesador, ahora: datetime) -> dict:
    """Revisa las citas sin respuesta. `procesador` es el ProcesadorAprobacion."""
    repo, mensajero = procesador.repo, procesador.mensajero
    cfg = _config(procesador.cfg)
    conteo = {"recordatorios": 0, "clientes_avisados": 0, "vencidas": 0}

    for cita in repo.citas_por_estado("pendiente_aprobacion"):
        eventos = repo.eventos_de_cita(cita["id"])
        envios = [i for i, e in enumerate(eventos) if e["tipo"] == "enviada_a_propietaria"]
        if not envios:
            continue  # nunca se le envio (sin PROPIETARIA_WHATSAPP): nada que recordar
        desde_envio = eventos[envios[-1]:]  # tras una reprogramacion, la cuenta empieza de nuevo
        recordatorios = [e for e in desde_envio if e["tipo"] == "recordatorio_propietaria"]
        ultimo_aviso = datetime.fromisoformat((recordatorios[-1] if recordatorios else desde_envio[0])["fecha"])
        espera = ahora - ultimo_aviso

        inicio = datetime.fromisoformat(cita["fecha_hora"]) if cita.get("fecha_hora") else None
        if inicio and inicio - ahora <= timedelta(hours=cfg["vence_horas_antes"]):
            procesador._rechazar(cita, _Vencida(), ahora)
            repo.registrar_evento(cita["id"], "vencida", {"motivo": "sin respuesta de la propietaria a tiempo"})
            if procesador.propietaria:
                mensajero.enviar(procesador.propietaria,
                                 f"⌛ La cita #{cita['id']} ({mensajes.fecha_legible(inicio)}) venció sin respuesta. "
                                 "Le ofrecí otros horarios al cliente.")
            conteo["vencidas"] += 1
            continue

        if espera < timedelta(minutes=cfg["recordatorio_min"]):
            continue
        if len(recordatorios) < cfg["max_recordatorios"]:
            if not (procesador.propietaria and _en_horas_de_aviso(ahora, cfg)):
                continue
            n = len(recordatorios) + 1
            texto = mensajes.resumen_para_propietaria(
                cita, f"⏰ Recordatorio {n}: la cita #{cita['id']} sigue esperando tu respuesta")
            msg_id = mensajero.enviar(procesador.propietaria, texto)
            if msg_id:
                # Citar el recordatorio funciona igual que citar el primer resumen.
                repo.actualizar_cita(cita["id"], msg_aprobacion_id=msg_id)
            repo.registrar_evento(cita["id"], "recordatorio_propietaria", {"n": n, "wa_id": msg_id})
            conteo["recordatorios"] += 1
        elif not any(e["tipo"] == "cliente_avisado_demora" for e in desde_envio):
            mensajero.enviar(cita["cliente_telefono"],
                             "Su solicitud sigue en revisión 🙏 Estamos con mucho trabajo en este momento; "
                             "apenas la confirme le aviso por aquí.")
            repo.registrar_evento(cita["id"], "cliente_avisado_demora")
            conteo["clientes_avisados"] += 1

    if any(conteo.values()):
        logger.info("Seguimiento de aprobaciones: %s", conteo)
    return conteo


class _Vencida:
    """Decision minima para reutilizar el camino de rechazo."""
    motivo = "sin respuesta de la propietaria antes de la hora de la cita"
