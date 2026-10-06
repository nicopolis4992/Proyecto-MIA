"""
SCRUM-77: procesar la aprobacion, rechazo o modificacion de la propietaria.

Flujo de estados (campo `estado` de SCRUM-74):
    pendiente_aprobacion -> aprobada -> confirmada         (aprobar)
    pendiente_aprobacion -> rechazada                      (rechazar; se ofrecen otros horarios)
    pendiente_aprobacion -> propuesta_cliente (ciclo+1)    (modificar hora/precio)
    propuesta_cliente    -> confirmada | en_reprogramacion (lo decide el CLIENTE, agente_agenda)

La propietaria rara vez responde "si"/"no" literal ("listo", "dale nomas",
"a las 12 estaria bien", "en 2$ le dejo el transporte"). Respuestas cortas
y obvias se resuelven con una lista cerrada; el resto lo interpreta Gemini
con salida estructurada.

Una modificacion NO confirma la cita: el cambio se le PROPONE al cliente,
porque el horario o el precio nuevos pueden no servirle. A la propietaria se
le muestra lo que el sistema entendio, para que corrija si hace falta.

Ademas, cuando el agente RAG no sabe responder algo, la pregunta del cliente
se reenvia a la propietaria; si ella responde citando ese aviso, su
respuesta se le reenvia al cliente (relevo de consultas).
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from google.genai import types

from app.agenda import mensajes
from app.agenda.calendario import registrar_en_calendario
from app.agenda.disponibilidad import proponer_alternativas, validar_horario
from app.config import MODELO_LLM, ZONA_HORARIA

logger = logging.getLogger("agenda.aprobacion")

_APROBAR = {"listo", "si", "ok", "okey", "dale", "dale nomas", "aprobado", "aprobada", "va",
            "de una", "confirmado", "confirma", "confirmalo", "perfecto", "esta bien", "si dale",
            "listo dale", "👍", "si listo"}
_RECHAZAR = {"no", "rechazado", "rechazada", "no puedo", "no se puede", "rechaza", "no dale"}
# Al reabrir una reserva ya cotizada no se vuelve a preguntar por la mascota.
_TODO_PREGUNTADO = ["tamano", "raza_o_grupo_manto", "estado_manto", "comportamiento"]


def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^\w\s👍]", "", t).strip()


@dataclass
class Decision:
    tipo: str                               # aprobar | rechazar | modificar | no_entendido
    nueva_fecha_hora: datetime | None = None
    nuevo_total: float | None = None
    nuevo_costo_transporte: float | None = None
    motivo: str | None = None
    origen: str = "reglas"


PROMPT = """Eres el modulo que interpreta la respuesta de la propietaria de una
peluqueria canina a una solicitud de cita que el sistema le envio para aprobar.

Clasifica su respuesta en:
- "aprobar": acepta la cita tal cual ("listo", "dale nomas", "ok mandale").
- "rechazar": no acepta y no propone un cambio concreto ("no puedo ese dia",
  "no, estoy llena").
- "modificar": acepta pero cambia algo concreto: la hora/fecha
  ("a las 12 estaria bien" -> misma fecha a las 12:00), el precio total
  ("cobrale 20" -> nuevo_total 20) o el costo del transporte
  ("en 2$ le dejo el transporte" -> nuevo_costo_transporte 2).
- "no_entendido": no se puede saber que quiere.

nueva_fecha_hora en formato ISO 8601 (YYYY-MM-DDTHH:MM) usando la fecha de la
cita como referencia cuando solo cambia la hora. Interpreta horas sin am/pm
dentro del horario laboral (ej. "a las 3" = 15:00). motivo: frase corta si
la propietaria da una razon. Campos que no apliquen: null."""

ESQUEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "tipo": types.Schema(type=types.Type.STRING,
                             enum=["aprobar", "rechazar", "modificar", "no_entendido"]),
        "nueva_fecha_hora": types.Schema(type=types.Type.STRING, nullable=True),
        "nuevo_total": types.Schema(type=types.Type.NUMBER, nullable=True),
        "nuevo_costo_transporte": types.Schema(type=types.Type.NUMBER, nullable=True),
        "motivo": types.Schema(type=types.Type.STRING, nullable=True),
    },
    required=["tipo", "nueva_fecha_hora", "nuevo_total", "nuevo_costo_transporte", "motivo"],
)


def interpretar_respuesta(texto: str, cita: dict, client) -> Decision:
    norm = _normalizar(texto)
    if norm in _APROBAR:
        return Decision("aprobar")
    if norm in _RECHAZAR:
        return Decision("rechazar")

    contexto = (f"Cita propuesta: {mensajes.fecha_legible(cita.get('fecha_hora'))} "
                f"(ISO {cita.get('fecha_hora')}), total {mensajes.texto_total(cita)}, "
                f"modalidad {cita['modalidad']}.\nRespuesta de la propietaria: {texto}")
    resp = client.models.generate_content(
        model=MODELO_LLM, contents=contexto,
        config=types.GenerateContentConfig(
            system_instruction=PROMPT, response_mime_type="application/json",
            response_schema=ESQUEMA, temperature=0.0),
    )
    d = json.loads(resp.text)
    fecha = None
    if d.get("nueva_fecha_hora"):
        try:
            fecha = datetime.fromisoformat(d["nueva_fecha_hora"])
            if fecha.tzinfo is None:
                fecha = fecha.replace(tzinfo=ZONA_HORARIA)
        except ValueError:
            pass
    tipo = d["tipo"]
    if tipo == "modificar" and not (fecha or d.get("nuevo_total") is not None
                                    or d.get("nuevo_costo_transporte") is not None):
        tipo = "no_entendido"
    return Decision(tipo, fecha, d.get("nuevo_total"), d.get("nuevo_costo_transporte"),
                    d.get("motivo"), origen="llm")


class ProcesadorAprobacion:
    def __init__(self, client, repo, mensajero, cotizador, cfg_agenda: dict, propietaria: str,
                 calendario=None):
        self.client, self.repo, self.mensajero = client, repo, mensajero
        self.cotizador, self.cfg, self.propietaria = cotizador, cfg_agenda, propietaria
        self.calendario = calendario

    # -- seleccion de la cita a la que responde -----------------------------

    def _cita_objetivo(self, id_citado: str | None) -> tuple[dict | None, str | None]:
        if id_citado:
            cita = self.repo.cita_por_mensaje_aprobacion(id_citado)
            if cita and cita["estado"] in ("pendiente_aprobacion", "propuesta_cliente"):
                return cita, None
        pendientes = self.repo.citas_por_estado("pendiente_aprobacion")
        if not pendientes:
            return None, "No tienes citas pendientes de aprobación 🙂"
        if len(pendientes) > 1:
            ids = ", ".join(f"#{c['id']}" for c in pendientes)
            return None, (f"Tienes {len(pendientes)} citas pendientes ({ids}). "
                          "Responde citando (deslizando) el mensaje de la cita que quieres aprobar.")
        return pendientes[0], None

    # -- entrada principal --------------------------------------------------

    def procesar(self, texto: str, id_citado: str | None = None, ahora: datetime | None = None) -> str | None:
        if _normalizar(texto) in {"pendientes", "citas", "citas pendientes"}:
            return self._listar_pendientes()

        relevo = self._relevar_consulta(texto, id_citado)
        if relevo:
            return relevo

        cita, aviso = self._cita_objetivo(id_citado)
        if cita is None:
            return aviso

        decision = interpretar_respuesta(texto, cita, self.client)
        self.repo.registrar_evento(cita["id"], "respuesta_propietaria",
                                   {"texto": texto, "decision": decision.tipo, "origen": decision.origen})
        logger.info("Cita #%s: decision=%s (%s)", cita["id"], decision.tipo, decision.origen)

        if decision.tipo == "aprobar":
            return self._aprobar(cita)
        if decision.tipo == "rechazar":
            return self._rechazar(cita, decision, ahora)
        if decision.tipo == "modificar":
            return self._modificar(cita, decision)
        return ("No te entendí 😅. Responde \"listo\" para aprobar, \"no\" para rechazar, "
                "o indícame el cambio (hora o precio).")

    # -- relevo de consultas sin respuesta -----------------------------------

    def registrar_consulta(self, msg_id: str | None, cliente: str, pregunta: str) -> None:
        """Guarda a que cliente corresponde un aviso de "pregunta sin respuesta"."""
        if not msg_id:
            return
        sesion = self.repo.obtener_sesion(self.propietaria)
        consultas = sesion.setdefault("consultas", {})
        consultas[msg_id] = {"cliente": cliente, "pregunta": pregunta}
        sesion["consultas"] = dict(list(consultas.items())[-20:])  # solo las recientes
        sesion["ultima_consulta"] = msg_id
        self.repo.guardar_sesion(self.propietaria, sesion)

    def _relevar_consulta(self, texto: str, id_citado: str | None) -> str | None:
        sesion = self.repo.obtener_sesion(self.propietaria)
        consultas = sesion.get("consultas", {})
        msg_id = id_citado if id_citado in consultas else None
        # Sin cita citada: si no hay citas por aprobar, la respuesta es para la
        # ultima consulta (salvo que sea una palabra de aprobacion/rechazo).
        if (msg_id is None and sesion.get("ultima_consulta") in consultas
                and not self.repo.citas_por_estado("pendiente_aprobacion")
                and _normalizar(texto) not in _APROBAR | _RECHAZAR):
            msg_id = sesion["ultima_consulta"]
        if msg_id is None:
            return None
        consulta = consultas.pop(msg_id)
        if sesion.get("ultima_consulta") == msg_id:
            sesion["ultima_consulta"] = None
        self.repo.guardar_sesion(self.propietaria, sesion)
        self.mensajero.enviar(consulta["cliente"], f"💬 Respuesta de la propietaria: {texto}")
        return f"📨 Se lo envié al cliente {consulta['cliente']} (preguntó: \"{consulta['pregunta']}\")."

    def _listar_pendientes(self) -> str:
        pendientes = self.repo.citas_por_estado("pendiente_aprobacion")
        if not pendientes:
            return "No tienes citas pendientes de aprobación 🙂"
        return "Pendientes:\n" + "\n".join(
            f"#{c['id']} — {mensajes.fecha_legible(c['fecha_hora'])} — "
            f"{', '.join(m.get('nombre') or 'mascota' for m in c['mascotas'])}" for c in pendientes)

    def _aprobar(self, cita: dict) -> str:
        self.repo.actualizar_cita(cita["id"], estado="aprobada")
        self.repo.registrar_evento(cita["id"], "aprobada")
        texto = mensajes.confirmacion_cliente(cita)
        msg_id = self.mensajero.enviar(cita["cliente_telefono"], texto)
        # SCRUM-78: la cita pasa a confirmada cuando el mensaje sale (o queda
        # encolado para reintento, SCRUM-87: no se pierde).
        self.repo.actualizar_cita(cita["id"], estado="confirmada")
        self.repo.registrar_evento(cita["id"], "confirmada",
                                   {"mensaje_cliente": texto, "wa_id": msg_id, "encolado": msg_id is None})
        self._marcar_cita_activa(cita)
        extra = registrar_en_calendario(self.repo, self.calendario, cita)
        return f"✅ Cita #{cita['id']} confirmada. Ya le avisé al cliente.{extra}"

    def _rechazar(self, cita: dict, decision: Decision, ahora: datetime | None) -> str:
        self.repo.actualizar_cita(cita["id"], estado="rechazada")
        self.repo.registrar_evento(cita["id"], "rechazada", {"motivo": decision.motivo})
        desde = datetime.fromisoformat(cita["fecha_hora"]) if cita.get("fecha_hora") else ahora
        duracion = (cita.get("cotizacion") or {}).get("duracion_agenda_min", 60)
        from app.agenda.disponibilidad import ocupado_combinado

        alternativas = proponer_alternativas(desde, duracion, cita["modalidad"], self.cotizador, self.cfg,
                                             ocupado_combinado(self.repo, self.calendario), ahora)
        self.mensajero.enviar(cita["cliente_telefono"],
                              mensajes.reprogramacion_cliente(cita, alternativas))
        # El cliente queda de nuevo en el flujo de agenda, con todo lo que ya
        # dio menos el horario, para que solo tenga que elegir otro.
        sesion = self.repo.obtener_sesion(cita["cliente_telefono"])
        sesion.update(
            flujo="agendando", cita_en_aprobacion=None, preguntado=_TODO_PREGUNTADO,
            alternativas=[a.isoformat() for a in alternativas],
            reserva={"mascotas": cita["mascotas"], "fecha_hora": None, "modalidad": cita["modalidad"],
                     "sector": cita.get("sector"), "cliente_nombre": cita.get("cliente_nombre")},
            revision_manual=cita.get("requiere_revision_manual", False),
        )
        self.repo.guardar_sesion(cita["cliente_telefono"], sesion)
        ofrecidos = ", ".join(mensajes.fecha_legible(a) for a in alternativas) or "ninguno (le pedí otro horario)"
        return f"❌ Cita #{cita['id']} rechazada. Le ofrecí al cliente: {ofrecidos}."

    def _modificar(self, cita: dict, d: Decision) -> str | None:
        cambios: dict = {}
        if d.nueva_fecha_hora:
            cambios["fecha_hora"] = d.nueva_fecha_hora
        if d.nuevo_total is not None:
            cambios["total_acordado"] = float(d.nuevo_total)
        elif d.nuevo_costo_transporte is not None and cita.get("cotizacion"):
            # La propietaria fija el traslado: se recalcula el total con el
            # motor en vez de restar a mano (el total puede ser un rango).
            cambios["cotizacion"] = self.cotizador.recalcular_total(
                dict(cita["cotizacion"]), float(d.nuevo_costo_transporte))
        ciclo = cita.get("ciclo_aprobacion", 1) + 1
        self.repo.actualizar_cita(cita["id"], ciclo_aprobacion=ciclo, estado="propuesta_cliente", **cambios)
        self.repo.registrar_evento(cita["id"], "modificada", {k: str(v) for k, v in cambios.items()})
        actualizada = self.repo.obtener_cita(cita["id"])

        # El cambio se le propone al cliente: el nuevo horario o precio puede
        # no servirle, asi que la cita NO se confirma hasta que acepte.
        self.mensajero.enviar(cita["cliente_telefono"], mensajes.propuesta_cliente(actualizada))
        self.repo.registrar_evento(cita["id"], "propuesta_enviada_al_cliente")
        sesion = self.repo.obtener_sesion(cita["cliente_telefono"])
        sesion.update(propuesta_cita=cita["id"], cita_en_aprobacion=None)
        self.repo.guardar_sesion(cita["cliente_telefono"], sesion)

        respuesta = (f"📨 Le propuse el cambio al cliente: {mensajes.fecha_legible(actualizada['fecha_hora'])} · "
                     f"Total {mensajes.texto_total(actualizada)}. Te aviso cuando responda. "
                     "(Si entendí mal, escríbeme el cambio correcto.)")
        if "fecha_hora" in cambios:
            duracion = (cita.get("cotizacion") or {}).get("duracion_agenda_min", 60)
            ok, motivo = validar_horario(d.nueva_fecha_hora, duracion, cita["modalidad"], self.cotizador, self.cfg)
            if not ok:
                respuesta = f"⚠️ Ojo: el nuevo horario {motivo}.\n" + respuesta
        return respuesta

    def _marcar_cita_activa(self, cita: dict) -> None:
        """Tras confirmar, la sesion recuerda la cita para poder cambiarla o cancelarla."""
        sesion = self.repo.obtener_sesion(cita["cliente_telefono"])
        sesion.update(cita_en_aprobacion=None, propuesta_cita=None, cita_activa=cita["id"])
        self.repo.guardar_sesion(cita["cliente_telefono"], sesion)
