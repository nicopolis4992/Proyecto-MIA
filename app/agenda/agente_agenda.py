"""
Agente de agenda conversacional (reemplaza nodo_agenda_stub).

Recolecta, a lo largo de varios mensajes, los datos que la cita necesita
(servicio, nombre de la mascota, tamano, modalidad, sector, fecha y hora),
cotiza con el motor parametrizado, valida el horario y registra la cita en
estado pendiente_aprobacion enviando el resumen a la propietaria. NUNCA
confirma la cita: eso solo ocurre en aprobacion.py cuando ella aprueba.

Por que existe aqui: el epic de Agenda (SCRUM-55) es de Daniel Ocampo, pero
sin un flujo minimo de punta a punta no hay prototipo para el 4-oct. Los
puntos de integracion pendientes son:
  - disponibilidad.ocupado -> Google Calendar (SCRUM-72)
  - mensajes.resumen_para_propietaria -> SCRUM-75
  - envio con fallback a correo -> SCRUM-76 / SCRUM-86

Extraccion: una llamada a Gemini con salida estructurada que recibe el
estado actual de la reserva y el mensaje, y devuelve la reserva completa
actualizada. Las preguntas al cliente salen de plantillas (no del LLM).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from google.genai import types

from app.agenda import mensajes
from app.agenda.disponibilidad import ocupado_segun_repositorio, proponer_alternativas, validar_horario
from app.config import MODELO_LLM, ZONA_HORARIA
from app.cotizacion.motor_cotizacion import ErrorTarifario, Mascota, Motor, Solicitud

logger = logging.getLogger("agenda")

SERVICIOS = ["bano", "bano_corte", "corte_higienico", "deslanado"]

PROMPT = """Eres el modulo que extrae datos para agendar una cita en una
peluqueria canina de Quito. Recibes la RESERVA ACTUAL (JSON) y el MENSAJE del
cliente. Devuelve la reserva COMPLETA actualizada: conserva los datos que ya
estaban y agrega o corrige solo lo que el mensaje dice explicitamente. No
inventes datos.

- servicio: "bano" (bano/higiene), "bano_corte" (bano y corte, grooming
  completo, peluqueada), "corte_higienico", "deslanado".
- tamano: "pequeno" (hasta 9 kg), "mediano" (9-18 kg), "grande" (18-45 kg),
  solo si el cliente lo dice o da el peso (peso_kg).
- pelaje: "corto", "largo", "rizado", "doble_capa", solo si lo dice.
- estado_manto: "sin_nudos", "leve", "moderado", "severo", solo si lo dice.
- Si menciona varias mascotas, una entrada por mascota.
- fecha_hora: ISO 8601 "YYYY-MM-DDTHH:MM" resolviendo expresiones relativas
  ("manana a las 3" = dia siguiente 15:00) respecto a FECHA ACTUAL. Horas sin
  am/pm se interpretan entre 08:00 y 19:59.
- modalidad: "salon" si lo lleva el cliente, "puerta_a_puerta" si pide que
  lo retiren o recojan a domicilio.
- sector: barrio o sector de Quito si lo menciona.
- eligio_alternativa: si el cliente elige una de las OPCIONES OFRECIDAS
  (por numero o describiendola), su numero (1, 2, 3). Si no, null.
- cancelar: true solo si dice que ya no quiere agendar."""

_MASCOTA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "nombre": types.Schema(type=types.Type.STRING, nullable=True),
        "servicio": types.Schema(type=types.Type.STRING, enum=SERVICIOS, nullable=True),
        "tamano": types.Schema(type=types.Type.STRING, enum=["pequeno", "mediano", "grande"], nullable=True),
        "peso_kg": types.Schema(type=types.Type.NUMBER, nullable=True),
        "pelaje": types.Schema(type=types.Type.STRING, enum=["corto", "largo", "rizado", "doble_capa"], nullable=True),
        "estado_manto": types.Schema(type=types.Type.STRING, enum=["sin_nudos", "leve", "moderado", "severo"], nullable=True),
    },
    required=["nombre", "servicio", "tamano", "peso_kg", "pelaje", "estado_manto"],
)
ESQUEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "mascotas": types.Schema(type=types.Type.ARRAY, items=_MASCOTA),
        "fecha_hora": types.Schema(type=types.Type.STRING, nullable=True),
        "modalidad": types.Schema(type=types.Type.STRING, enum=["salon", "puerta_a_puerta"], nullable=True),
        "sector": types.Schema(type=types.Type.STRING, nullable=True),
        "cliente_nombre": types.Schema(type=types.Type.STRING, nullable=True),
        "eligio_alternativa": types.Schema(type=types.Type.INTEGER, nullable=True),
        "cancelar": types.Schema(type=types.Type.BOOLEAN),
    },
    required=["mascotas", "fecha_hora", "modalidad", "sector", "cliente_nombre",
              "eligio_alternativa", "cancelar"],
)


def reserva_vacia() -> dict:
    return {"mascotas": [], "fecha_hora": None, "modalidad": None, "sector": None, "cliente_nombre": None}


@dataclass
class AgenteAgenda:
    client: object
    repo: object
    mensajero: object
    motor: Motor
    cfg: dict
    propietaria: str

    # -- extraccion ---------------------------------------------------------

    def extraer(self, mensaje: str, reserva: dict, alternativas: list[str], ahora: datetime) -> dict:
        opciones = "\n".join(f"{i}. {a}" for i, a in enumerate(alternativas, 1)) or "ninguna"
        contenido = (
            f"FECHA ACTUAL: {mensajes.fecha_legible(ahora)} ({ahora.strftime('%Y-%m-%dT%H:%M')})\n"
            f"OPCIONES OFRECIDAS:\n{opciones}\n"
            f"RESERVA ACTUAL: {json.dumps(reserva, ensure_ascii=False)}\n"
            f"MENSAJE: {mensaje}"
        )
        resp = self.client.models.generate_content(
            model=MODELO_LLM, contents=contenido,
            config=types.GenerateContentConfig(
                system_instruction=PROMPT, response_mime_type="application/json",
                response_schema=ESQUEMA, temperature=0.0),
        )
        return json.loads(resp.text)

    # -- turno de conversacion ----------------------------------------------

    def atender(self, telefono: str, mensaje: str, ahora: datetime) -> str:
        sesion = self.repo.obtener_sesion(telefono)
        sesion.setdefault("reserva", reserva_vacia())
        sesion["flujo"] = "agendando"
        alternativas = sesion.get("alternativas") or []

        datos = self.extraer(mensaje, sesion["reserva"], alternativas, ahora)
        logger.info("Agenda | %s | extraido=%s", telefono, datos)

        if datos.get("cancelar"):
            self.repo.guardar_sesion(telefono, {k: v for k, v in sesion.items()
                                                if k == "cita_en_aprobacion"})
            return "Entendido, no agendo nada por ahora. Cuando guste me escribe 🐾"

        reserva = self._fusionar(sesion["reserva"], datos)
        n = datos.get("eligio_alternativa")
        if n and 1 <= n <= len(alternativas):
            reserva["fecha_hora"] = alternativas[n - 1]
        sesion["reserva"] = reserva

        pregunta = self._siguiente_pregunta(sesion)
        if pregunta:
            self.repo.guardar_sesion(telefono, sesion)
            return pregunta
        return self._cerrar_reserva(telefono, sesion, ahora)

    def _fusionar(self, anterior: dict, nuevo: dict) -> dict:
        r = dict(anterior)
        for campo in ("fecha_hora", "modalidad", "sector", "cliente_nombre"):
            if nuevo.get(campo):
                r[campo] = nuevo[campo]
        mascotas = []
        previas = anterior.get("mascotas") or []
        for i, m in enumerate(nuevo.get("mascotas") or []):
            base = dict(previas[i]) if i < len(previas) else {}
            for k, v in m.items():
                if v is not None:
                    base[k] = v
            if base.get("peso_kg") and not base.get("tamano"):
                try:
                    base["tamano"] = self.motor.tamano_por_peso(float(base["peso_kg"]))
                except ErrorTarifario:
                    pass
            mascotas.append(base)
        # Si el LLM devuelve menos mascotas que antes, no se pierden datos.
        mascotas.extend(previas[len(mascotas):])
        r["mascotas"] = mascotas
        if r.get("fecha_hora"):
            try:
                f = datetime.fromisoformat(r["fecha_hora"])
                r["fecha_hora"] = (f if f.tzinfo else f.replace(tzinfo=ZONA_HORARIA)).isoformat()
            except ValueError:
                r["fecha_hora"] = None
        return r

    def _siguiente_pregunta(self, sesion: dict) -> str | None:
        r = sesion["reserva"]
        mascotas = r["mascotas"]
        if not mascotas or any(not m.get("servicio") for m in mascotas):
            return ("¡Con gusto le agendo! 🐶 ¿Qué servicio necesita: baño, baño y corte, "
                    "corte higiénico o deslanado?")
        sin_nombre = [m for m in mascotas if not m.get("nombre")]
        if sin_nombre:
            return "¿Cómo se llama su perrito?" if len(mascotas) == 1 else "¿Cómo se llaman sus perritos?"
        sin_tamano = [m for m in mascotas if not m.get("tamano")]
        if sin_tamano and not sesion.get("revision_manual") and not sesion.get("pidio_tamano"):
            sesion["pidio_tamano"] = True
            return (f"Para darle el valor, ¿me envía una foto de cuerpo entero de {sin_tamano[0]['nombre']}? "
                    "O si prefiere, dígame si es pequeño, mediano o grande (o cuánto pesa).")
        if not r.get("modalidad"):
            return "¿Lo trae usted al salón o prefiere el servicio puerta a puerta (lo retiramos y entregamos)?"
        if r["modalidad"] == "puerta_a_puerta" and not r.get("sector"):
            return "¿En qué sector de Quito lo retiramos?"
        if not r.get("fecha_hora"):
            return "¿Qué día y a qué hora le gustaría la cita?"
        return None

    def _solicitud(self, r: dict) -> Solicitud:
        return Solicitud(
            mascotas=[Mascota(servicio=m["servicio"], nombre=m.get("nombre"), tamano=m.get("tamano"),
                              pelaje=m.get("pelaje"), estado_manto=m.get("estado_manto"))
                      for m in r["mascotas"]],
            modalidad=r["modalidad"],
            # La zona exacta depende de la distancia; la propietaria la ajusta
            # al aprobar si el sector no es cercano.
            zona="zona_1" if r["modalidad"] == "puerta_a_puerta" else None,
            fecha_hora=datetime.fromisoformat(r["fecha_hora"]).replace(tzinfo=None),
        )

    def _cerrar_reserva(self, telefono: str, sesion: dict, ahora: datetime) -> str:
        r = sesion["reserva"]
        try:
            cotizacion = self.motor.cotizar(self._solicitud(r))
        except ErrorTarifario as exc:
            self.repo.guardar_sesion(telefono, sesion)
            logger.warning("Cotizacion invalida: %s", exc)
            if "no aplica a pelaje" in str(exc):
                for m in r["mascotas"]:
                    if m.get("servicio") == "deslanado":
                        m["servicio"] = None
                self.repo.guardar_sesion(telefono, sesion)
                return ("El deslanado solo aplica a perritos de pelo largo o doble capa. "
                        "¿Le parece mejor un baño o un baño y corte?")
            return "Tuve un problema calculando el valor; le paso con la propietaria para ayudarle."

        inicio = datetime.fromisoformat(r["fecha_hora"])
        duracion = cotizacion["duracion_total_estimada_min"]
        ocupado = ocupado_segun_repositorio(self.repo)
        ok, motivo = validar_horario(inicio, duracion, r["modalidad"], self.motor, self.cfg, ocupado, ahora)
        if not ok:
            alternativas = proponer_alternativas(inicio, duracion, r["modalidad"], self.motor, self.cfg,
                                                 ocupado, ahora)
            sesion["alternativas"] = [a.isoformat() for a in alternativas]
            r["fecha_hora"] = None
            self.repo.guardar_sesion(telefono, sesion)
            return mensajes.reprogramacion_cliente({"fecha_hora": inicio.isoformat()}, alternativas, motivo)

        cita_id = self.repo.crear_cita(
            cliente_telefono=telefono, cliente_nombre=r.get("cliente_nombre"),
            mascotas=r["mascotas"], fecha_hora=inicio, modalidad=r["modalidad"],
            zona="zona_1" if r["modalidad"] == "puerta_a_puerta" else None, sector=r.get("sector"),
            cotizacion=cotizacion, requiere_revision_manual=bool(sesion.get("revision_manual")),
        )
        if sesion.get("traza_foto"):
            self.repo.registrar_evento(cita_id, "cotizacion_por_foto", sesion["traza_foto"])
        cita = self.repo.obtener_cita(cita_id)
        if self.propietaria:
            msg_id = self.mensajero.enviar(self.propietaria, mensajes.resumen_para_propietaria(cita))
            self.repo.actualizar_cita(cita_id, msg_aprobacion_id=msg_id)
            self.repo.registrar_evento(cita_id, "enviada_a_propietaria", {"wa_id": msg_id})
        else:
            logger.error("PROPIETARIA_WHATSAPP no configurado: la cita #%s no se envio a aprobar", cita_id)

        self.repo.guardar_sesion(telefono, {"cita_en_aprobacion": cita_id})
        return (f"¡Perfecto! Tengo todo para el {mensajes.fecha_legible(inicio)}. "
                f"{cotizacion['mensaje_sugerido']} Le confirmo en un momento, apenas se revise la agenda 🙌")
