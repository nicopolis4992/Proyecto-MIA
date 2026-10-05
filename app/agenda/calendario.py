"""
Integracion minima con Google Calendar.

- registrar_cita: cuando la propietaria APRUEBA una cita (SCRUM-77/78), se
  crea el evento en el calendario exclusivo del negocio.
- ocupado: consulta free/busy para no proponer horarios ya tomados.

Es la base para SCRUM-72 (Daniel Ocampo): la consulta de disponibilidad
completa y las reglas de agenda son suyas; aqui solo se escribe la cita
aprobada y se lee la ocupacion.

Configuracion (si falta, todo es no-op y el sistema sigue funcionando):
    GOOGLE_CALENDAR_ID            id del calendario (ej. xxxx@group.calendar.google.com)
    GOOGLE_SERVICE_ACCOUNT_JSON   contenido del JSON de la cuenta de servicio
      o GOOGLE_SERVICE_ACCOUNT_FILE  ruta al archivo JSON
El calendario debe estar compartido con el correo de la cuenta de servicio
con permiso "Hacer cambios en eventos".
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta

from app.agenda import mensajes

logger = logging.getLogger("calendario")

API = "https://www.googleapis.com/calendar/v3"
ALCANCE = ["https://www.googleapis.com/auth/calendar"]
# Colores de Google Calendar por modalidad (ids de la paleta de eventos).
COLOR = {"salon": "2", "puerta_a_puerta": "6"}


class CalendarioGoogle:
    def __init__(self, calendar_id: str, credenciales_info: dict):
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_info(credenciales_info, scopes=ALCANCE)
        self.sesion = AuthorizedSession(creds)
        self.calendar_id = calendar_id

    def registrar_cita(self, cita: dict) -> str:
        inicio = datetime.fromisoformat(cita["fecha_hora"])
        duracion = (cita.get("cotizacion") or {}).get("duracion_agenda_min", 60)
        nombres = ", ".join(m.get("nombre") or "mascota" for m in cita["mascotas"])
        servicios = ", ".join(m.get("servicio_nombre", "") for m in (cita.get("cotizacion") or {}).get("mascotas", []))
        modalidad = "🚗 puerta a puerta" if cita["modalidad"] == "puerta_a_puerta" else "salón"
        evento = {
            "summary": f"🐾 {nombres} — {servicios} ({modalidad})",
            "description": (f"Cita #{cita['id']} aprobada por la propietaria.\n"
                            f"Cliente: {cita['cliente_telefono']}\n"
                            f"Total: {mensajes.texto_total(cita)}\n"
                            + (f"Sector: {cita['sector']}\n" if cita.get("sector") else "")
                            + "Registrado automáticamente por el asistente de WhatsApp."),
            "start": {"dateTime": inicio.isoformat(), "timeZone": "America/Guayaquil"},
            "end": {"dateTime": (inicio + timedelta(minutes=duracion)).isoformat(),
                    "timeZone": "America/Guayaquil"},
            "colorId": COLOR.get(cita["modalidad"], "1"),
        }
        r = self.sesion.post(f"{API}/calendars/{self.calendar_id}/events", json=evento, timeout=15)
        r.raise_for_status()
        return r.json()["id"]

    def ocupado(self, inicio: datetime, duracion_min: int) -> bool:
        cuerpo = {
            "timeMin": inicio.isoformat(),
            "timeMax": (inicio + timedelta(minutes=duracion_min)).isoformat(),
            "items": [{"id": self.calendar_id}],
        }
        r = self.sesion.post(f"{API}/freeBusy", json=cuerpo, timeout=15)
        r.raise_for_status()
        return bool(r.json()["calendars"][self.calendar_id]["busy"])


def crear_calendario() -> CalendarioGoogle | None:
    calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "")
    info = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    archivo = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    if not calendar_id or not (info or archivo):
        logger.info("Google Calendar no configurado: las citas solo quedan en la base local.")
        return None
    try:
        datos = json.loads(info) if info else json.loads(open(archivo, encoding="utf-8").read())
        return CalendarioGoogle(calendar_id, datos)
    except Exception:  # noqa: BLE001 - una mala configuracion no debe tumbar el bot
        logger.exception("No se pudo inicializar Google Calendar")
        return None
