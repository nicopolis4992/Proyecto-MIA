"""
Agente de agenda conversacional (reemplaza nodo_agenda_stub).

Recolecta, a lo largo de varios mensajes, los datos que la cita necesita,
cotiza con el tarifario v2, valida el horario y registra la cita en estado
pendiente_aprobacion enviando el resumen a la propietaria. NUNCA confirma la
cita: eso solo ocurre en aprobacion.py cuando ella aprueba.

Que se pregunta y en que orden:
1. Servicio y nombre de la mascota (siempre).
2. Los datos que mueven el precio, en el orden de impacto en USD que calcula
   el motor (normalmente tamano primero). Cada pregunta se hace UNA vez y en
   lenguaje de la clienta (tarifario_v2.json > preguntas_cliente). Si no sabe
   o no responde, se sigue con el rango: la propietaria ajusta al aprobar.
   Nudos y comportamiento se preguntan juntos para no alargar la charla.
3. Modalidad, sector (si es puerta a puerta) y fecha/hora.

Mestizos y cruces: la clienta puede decir "es mestizo", "cruce de schnauzer
con poodle" o describir el pelo ("le crece y hay que cortarlo"); el LLM lo
traduce a raza / grupo de manto y el motor hace el resto.

Por que existe aqui: el epic de Agenda (SCRUM-55) es de Daniel Ocampo, pero
sin un flujo minimo de punta a punta no hay prototipo. Puntos de integracion
pendientes: disponibilidad.ocupado -> Google Calendar (SCRUM-72),
mensajes.resumen_para_propietaria -> SCRUM-75, envio con correo -> SCRUM-76/86.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from google.genai import types

from app.agenda import mensajes
from app.agenda.disponibilidad import ocupado_combinado, proponer_alternativas, validar_horario
from app.config import MODELO_LLM, ZONA_HORARIA
from app.cotizacion.cotizador import Cotizador

logger = logging.getLogger("agenda")

CAMPOS_MOTOR = ("nombre", "servicio", "raza", "tamano", "grupo", "estado", "comportamiento", "peso_kg")
GRUPOS = ["A_maquina", "B_deslanado", "C_cepillado", "D_corto"]


def construir_prompt(cotizador: Cotizador) -> str:
    d = cotizador.datos
    servicios = "\n".join(f'  - "{k}": {v["nombre"]} (incluye {", ".join(v["incluye"])})'
                          for k, v in d["servicios"].items())
    pedidos = "\n".join(f'  - "{k}" -> "{v}"' for k, v in d["servicio_minimo_por_pedido"].items()
                        if not k.startswith("_"))
    grupos = "\n".join(f'  - "{k}": {v["como_lo_describe_la_clienta"]}'
                       for k, v in d["grupos_manto"].items() if not k.startswith("_"))
    return f"""Eres el modulo que extrae datos para agendar una cita en una
peluqueria canina de Quito. Recibes la RESERVA ACTUAL (JSON) y el MENSAJE de
la clienta. Devuelve la reserva COMPLETA actualizada: conserva lo que ya
estaba y agrega o corrige solo lo que el mensaje dice explicitamente. No
inventes datos.

servicio (por mascota):
{servicios}
  - "deslanado": retiro de subpelo (solo perros de doble capa).
Si pide algo puntual, usa el servicio minimo que lo incluye:
{pedidos}
Si solo dice "baño" sin mas detalle, deja servicio en null (se le pregunta).

raza: texto tal como lo dice la clienta (ej. "shitzu", "mestizo",
"cruce de schnauzer con poodle"). No la corrijas ni la inventes.
tamano: "pequeno" (hasta 9 kg), "mediano" (9-18 kg), "grande" (18-45 kg),
solo si lo dice; si da el peso, ponlo en peso_kg.
grupo (tipo de pelo), solo si la clienta describe el pelo:
{grupos}
estado: "sin_motas" (sin nudos), "moderado" (algunos nudos), "severo" (muy
enredado o apelmazado), solo si lo dice.
comportamiento: "tranquilo", "dificil" (nervioso, miedoso, inquieto),
"agresivo_declarado" (si dice que muerde o es agresivo).
Si menciona varias mascotas, una entrada por mascota.

fecha_hora: ISO 8601 "YYYY-MM-DDTHH:MM" resolviendo expresiones relativas
("manana a las 3" = dia siguiente 15:00) respecto a FECHA ACTUAL. Horas sin
am/pm se interpretan entre 08:00 y 19:59.
modalidad: "salon" si lo lleva la clienta, "puerta_a_puerta" si pide que lo
retiren o recojan a domicilio.
sector: barrio o sector de Quito si lo menciona.
eligio_alternativa: si elige una de las OPCIONES OFRECIDAS (por numero o
describiendola), su numero (1, 2, 3). Si no, null.
cancelar: true solo si dice que ya no quiere agendar."""


def construir_esquema(cotizador: Cotizador) -> types.Schema:
    S, T = types.Schema, types.Type
    mascota = S(
        type=T.OBJECT,
        properties={
            "nombre": S(type=T.STRING, nullable=True),
            "servicio": S(type=T.STRING, enum=cotizador.servicios_validos(), nullable=True),
            "raza": S(type=T.STRING, nullable=True),
            "tamano": S(type=T.STRING, enum=["pequeno", "mediano", "grande"], nullable=True),
            "peso_kg": S(type=T.NUMBER, nullable=True),
            "grupo": S(type=T.STRING, enum=GRUPOS, nullable=True),
            "estado": S(type=T.STRING, enum=["sin_motas", "moderado", "severo", "no_recuperable"], nullable=True),
            "comportamiento": S(type=T.STRING, enum=["tranquilo", "dificil", "agresivo_declarado"], nullable=True),
        },
        required=list(CAMPOS_MOTOR),
    )
    return S(
        type=T.OBJECT,
        properties={
            "mascotas": S(type=T.ARRAY, items=mascota),
            "fecha_hora": S(type=T.STRING, nullable=True),
            "modalidad": S(type=T.STRING, enum=["salon", "puerta_a_puerta"], nullable=True),
            "sector": S(type=T.STRING, nullable=True),
            "cliente_nombre": S(type=T.STRING, nullable=True),
            "eligio_alternativa": S(type=T.INTEGER, nullable=True),
            "cancelar": S(type=T.BOOLEAN),
        },
        required=["mascotas", "fecha_hora", "modalidad", "sector", "cliente_nombre",
                  "eligio_alternativa", "cancelar"],
    )


def reserva_vacia() -> dict:
    return {"mascotas": [], "fecha_hora": None, "modalidad": None, "sector": None, "cliente_nombre": None}


def para_motor(mascotas: list[dict]) -> list[dict]:
    return [{k: m[k] for k in CAMPOS_MOTOR if m.get(k) is not None} for m in mascotas]


@dataclass
class AgenteAgenda:
    client: object
    repo: object
    mensajero: object
    cotizador: Cotizador
    cfg: dict
    propietaria: str
    calendario: object = None

    def __post_init__(self):
        self._prompt = construir_prompt(self.cotizador)
        self._esquema = construir_esquema(self.cotizador)

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
                system_instruction=self._prompt, response_mime_type="application/json",
                response_schema=self._esquema, temperature=0.0),
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
            self._terminar(telefono, sesion)
            return "Entendido, no agendo nada por ahora. Cuando guste me escribe 🐾"

        reserva = self._fusionar(sesion["reserva"], datos)
        n = datos.get("eligio_alternativa")
        if n and 1 <= n <= len(alternativas):
            reserva["fecha_hora"] = alternativas[n - 1]
        sesion["reserva"] = reserva

        respuesta = self.continuar(telefono, sesion, ahora)
        return respuesta

    def continuar(self, telefono: str, sesion: dict, ahora: datetime) -> str:
        """Decide el siguiente paso con la reserva actual (tambien tras una foto)."""
        pregunta = self.siguiente_pregunta(sesion)
        if pregunta:
            self.repo.guardar_sesion(telefono, sesion)
            return pregunta
        return self._cerrar_reserva(telefono, sesion, ahora)

    def _fusionar(self, anterior: dict, nuevo: dict) -> dict:
        r = dict(anterior)
        for campo in ("fecha_hora", "modalidad", "sector", "cliente_nombre"):
            if nuevo.get(campo):
                r[campo] = nuevo[campo]
        previas = anterior.get("mascotas") or []
        mascotas = []
        for i, m in enumerate(nuevo.get("mascotas") or []):
            base = dict(previas[i]) if i < len(previas) else {}
            base.update({k: v for k, v in m.items() if v is not None})
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

    def siguiente_pregunta(self, sesion: dict) -> str | None:
        r = sesion["reserva"]
        mascotas = r["mascotas"]
        if not mascotas or any(not m.get("servicio") for m in mascotas):
            return "¡Con gusto le agendo! 🐶 " + self.cotizador.pregunta("servicio")
        if any(not m.get("nombre") for m in mascotas):
            return "¿Cómo se llama su perrito?" if len(mascotas) == 1 else "¿Cómo se llaman sus perritos?"

        # Rechazos y servicios que no aplican se resuelven antes de seguir.
        previa = self.cotizador.cotizar(para_motor(mascotas))
        for m_cot, m in zip(previa["mascotas"], mascotas):
            if m_cot.get("rechazada"):
                sesion["rechazo"] = m_cot["motivo"]
                return None
            if m_cot.get("no_aplica"):
                m["servicio"] = None
                return previa["mensaje_cliente"] + " ¿Le parece bien?"

        preguntado = sesion.setdefault("preguntado", [])
        for atributo in previa["preguntas_pendientes"]:
            if atributo in preguntado:
                continue
            if atributo == "tamano" and (sesion.get("revision_manual") or sesion.get("fotos_intentos")):
                continue
            if atributo in ("estado_manto", "comportamiento"):
                preguntado += ["estado_manto", "comportamiento"]
                return f"{self.cotizador.pregunta('estado_manto')} {self.cotizador.pregunta('comportamiento')}"
            preguntado.append(atributo)
            texto = self.cotizador.pregunta(atributo)
            nombre = mascotas[0].get("nombre")
            return texto if len(mascotas) > 1 or not nombre else f"Sobre {nombre}: {texto}"

        if not r.get("modalidad"):
            return "¿Lo trae usted al salón o prefiere el servicio puerta a puerta (lo retiramos y entregamos)?"
        if r["modalidad"] == "puerta_a_puerta" and not r.get("sector"):
            return "¿En qué sector de Quito lo retiramos?"
        if not r.get("fecha_hora"):
            return "¿Qué día y a qué hora le gustaría la cita?"
        return None

    def _terminar(self, telefono: str, sesion: dict) -> None:
        self.repo.guardar_sesion(telefono, {k: v for k, v in sesion.items() if k == "cita_en_aprobacion"})

    def _cerrar_reserva(self, telefono: str, sesion: dict, ahora: datetime) -> str:
        if sesion.get("rechazo"):
            motivo = sesion["rechazo"]
            self._terminar(telefono, sesion)
            return f"Lo siento mucho 🙏 {motivo} Gracias por escribirnos."

        r = sesion["reserva"]
        cotizacion = self.cotizador.cotizar(para_motor(r["mascotas"]), r["modalidad"], r.get("sector"))
        inicio = datetime.fromisoformat(r["fecha_hora"])
        duracion = cotizacion["duracion_agenda_min"]
        ocupado = ocupado_combinado(self.repo, self.calendario)
        ok, motivo = validar_horario(inicio, duracion, r["modalidad"], self.cotizador, self.cfg, ocupado, ahora)
        if not ok:
            alternativas = proponer_alternativas(inicio, duracion, r["modalidad"], self.cotizador, self.cfg,
                                                 ocupado, ahora)
            sesion["alternativas"] = [a.isoformat() for a in alternativas]
            r["fecha_hora"] = None
            self.repo.guardar_sesion(telefono, sesion)
            return mensajes.reprogramacion_cliente({"fecha_hora": inicio.isoformat()}, alternativas, motivo)

        cita_id = self.repo.crear_cita(
            cliente_telefono=telefono, cliente_nombre=r.get("cliente_nombre"),
            mascotas=r["mascotas"], fecha_hora=inicio, modalidad=r["modalidad"],
            zona=(cotizacion.get("traslado") or {}).get("zona"), sector=r.get("sector"),
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
                f"{cotizacion['mensaje_cliente']} Le confirmo en un momento, apenas se revise la agenda 🙌")
