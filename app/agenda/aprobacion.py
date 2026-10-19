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

Si la propietaria dice que ese dia u hora no puede, sin dar otra ("el lunes no
puedo, el total seria 22"), la misma cita se reabre: se anota el precio que
dio y al cliente se le ofrecen horarios de otro dia para que elija (prueba con
la propietaria, 17-oct: antes se le volvia a proponer el mismo lunes).

Una modificacion NO confirma la cita: el cambio se le PROPONE al cliente,
porque el horario o el precio nuevos pueden no servirle. A la propietaria se
le muestra lo que el sistema entendio, para que corrija si hace falta.

Ademas, cuando el agente RAG no sabe responder algo, la pregunta del cliente
se reenvia a la propietaria; si ella responde citando ese aviso, su
respuesta se le reenvia al cliente (relevo de consultas).

Despues del servicio, la propietaria registra lo que cobro ("cobré 22 a la
cita #5", o "cobré 22" citando el mensaje de la cita). Es el dato real contra
el que se mide la desviacion de la cotizacion (SCRUM-95). Se reconoce con
reglas: no gasta llamadas al LLM.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

from google.genai import types

from app.agenda import mensajes
from app.agenda.calendario import registrar_en_calendario
from app.agenda.disponibilidad import proponer_alternativas, validar_horario
from app.config import MODELO_LLM, ZONA_HORARIA
from app.config import ahora as reloj

logger = logging.getLogger("agenda.aprobacion")

_APROBAR = {"listo", "si", "ok", "okey", "dale", "dale nomas", "aprobado", "aprobada", "va",
            "de una", "confirmado", "confirma", "confirmalo", "perfecto", "esta bien", "si dale",
            "listo dale", "👍", "si listo"}
_RECHAZAR = {"no", "rechazado", "rechazada", "no puedo", "no se puede", "rechaza", "no dale"}
# Al reabrir una reserva ya cotizada no se vuelve a preguntar por la mascota.
_TODO_PREGUNTADO = ["tamano", "raza_o_grupo_manto", "estado_manto", "comportamiento", "salud"]
# "cobré 22", "le cobramos 18.50", "cobrado $30". No "cóbrale 20": eso es una
# modificacion del precio antes de aprobar.
_COBRO = re.compile(r"\bcobr(?:e|ado|amos)\b\D{0,15}?(\d+(?:[.,]\d{1,2})?)")
_NUM_CITA = re.compile(r"#\s*(\d+)|\bcita\s+(?:n[°o.]?\s*)?(\d+)\b")
_POR_COBRAR = {"por cobrar", "cobros pendientes", "pendientes de cobro"}
# Plan de contingencia: la propietaria apaga el bot y atiende ella.
_PAUSAR = {"pausar bot", "pausa bot", "pausar el bot", "apagar bot", "apagar el bot", "detener bot"}
# "el lunes no puedo", "ese dia estoy llena": no hay espacio y no propone otra hora.
_SIN_ESPACIO = re.compile(r"\bno (puedo|alcanzo|me alcanza|tengo (espacio|tiempo|cupo))|\bno hay (espacio|cupo)|"
                          r"\bestoy (llena|full|copada)|\bocupad")
_TODO_EL_DIA = re.compile(r"\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo|ese dia|todo el dia|hoy|manana)\b")
# Correccion del tamano tras ver la foto: "es grande", "es mediana".
_TAMANO_CORREGIDO = re.compile(r"\b(?:es|son)\s+(miniatura|pequen[oa]s?|median[oa]s?|grandes?|extragrandes?|"
                               r"extra grandes?)\b")
_TAMANO_MOTOR = {"mini": "pequeno", "peq": "pequeno", "med": "mediano", "gra": "grande", "ext": "grande"}
# Lo que dice la propietaria sobre una cita (hora, precio, aprobar). Si responde
# citando una consulta pero el texto es esto y hay una cita por aprobar, es para
# la cita (prueba del 18-oct: "cambialo para las 2pm, el precio a 20" se le
# reenvio al cliente que habia preguntado la direccion).
_DECISION_CITA = re.compile(r"\b(listo|aprobad[oa]|apruebo|rechaz|no puedo|cambi|a las \d|\d{1,2}\s*(am|pm)\b|"
                            r"precio|cobr|total|es (grande|median|pequen|miniatura|extragrande))")
_ACTIVAR = {"activar bot", "activar el bot", "reanudar bot", "encender bot", "prender bot", "prender el bot"}


def _sin_tildes(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def _normalizar(texto: str) -> str:
    return re.sub(r"[^\w\s👍]", "", _sin_tildes(texto)).strip()


def leer_cobro(texto: str) -> tuple[float, int | None] | None:
    """(monto, numero de cita o None) si el texto registra un cobro."""
    t = _sin_tildes(texto)
    numero = None
    m = _NUM_CITA.search(t)
    if m:
        numero = int(m.group(1) or m.group(2))
        t = t[:m.start()] + " " + t[m.end():]  # que el numero de cita no se lea como monto
    c = _COBRO.search(t)
    if not c:
        return None
    return float(c.group(1).replace(",", ".")), numero


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


def registrar_consulta(repo, propietaria: str, msg_id: str | None, cliente: str, pregunta: str) -> None:
    """Guarda a que cliente corresponde un mensaje reenviado a la propietaria (relevo)."""
    if not msg_id:
        return
    sesion = repo.obtener_sesion(propietaria)
    consultas = sesion.setdefault("consultas", {})
    consultas[msg_id] = {"cliente": cliente, "pregunta": pregunta}
    sesion["consultas"] = dict(list(consultas.items())[-20:])  # solo las recientes
    sesion["ultima_consulta"] = msg_id
    repo.guardar_sesion(propietaria, sesion)


class ProcesadorAprobacion:
    def __init__(self, client, repo, mensajero, cotizador, cfg_agenda: dict, propietaria: str,
                 calendario=None):
        self.client, self.repo, self.mensajero = client, repo, mensajero
        self.cotizador, self.cfg, self.propietaria = cotizador, cfg_agenda, propietaria
        self.calendario = calendario

    # -- seleccion de la cita a la que responde -----------------------------

    def _cita_objetivo(self, id_citado: str | None, numero: int | None = None) -> tuple[dict | None, str | None]:
        if numero is not None:
            # "listo #5": para responder sin citar (p. ej. desde el correo de respaldo).
            cita = self.repo.obtener_cita(numero)
            if cita and cita["estado"] in ("pendiente_aprobacion", "propuesta_cliente"):
                return cita, None
            return None, f"La cita #{numero} no está esperando tu aprobación."
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
        if _normalizar(texto) in _PAUSAR:
            self.repo.pausar_bot(True)
            logger.warning("Bot PAUSADO por la propietaria")
            return ("⏸️ Bot en pausa. Te reenvío cada mensaje de los clientes: respóndeme citándolo "
                    "y se lo paso. Escribe \"activar bot\" para que vuelva a atender.")
        if _normalizar(texto) in _ACTIVAR:
            self.repo.pausar_bot(False)
            logger.warning("Bot REACTIVADO por la propietaria")
            return "▶️ Bot activo otra vez: vuelvo a atender a los clientes."
        if _normalizar(texto) in {"pendientes", "citas", "citas pendientes"}:
            return self._listar_pendientes()
        if _normalizar(texto) in _POR_COBRAR:
            return self._listar_por_cobrar(ahora or reloj())
        cobro = leer_cobro(texto)
        if cobro:
            return self._registrar_cobro(*cobro, id_citado, ahora or reloj())

        relevo = self._relevar_consulta(texto, id_citado)
        if relevo:
            return relevo

        numero = _NUM_CITA.search(_sin_tildes(texto))
        if numero:
            texto = (texto[:numero.start()] + texto[numero.end():]).strip(" ,.:-") or texto
            numero = int(numero.group(1) or numero.group(2))
        cita, aviso = self._cita_objetivo(id_citado, numero)
        if cita is None:
            return aviso

        correccion = _TAMANO_CORREGIDO.search(_sin_tildes(texto))
        if correccion:
            # "es grande" tras ver la foto: se recotiza con ese tamaño (sin LLM).
            cita = self._corregir_tamano(cita, correccion.group(1))
            resto = (_sin_tildes(texto)[:correccion.start()] + _sin_tildes(texto)[correccion.end():]).strip(" ,.;")
            if not resto:
                return (f"📐 Cita #{cita['id']}: tamaño corregido. El precio queda en {mensajes.texto_total(cita)}. "
                        "Responde \"listo\" para aprobar o dime el precio.")
            texto = resto
        decision = interpretar_respuesta(texto, cita, self.client)
        self.repo.registrar_evento(cita["id"], "respuesta_propietaria",
                                   {"texto": texto, "decision": decision.tipo, "origen": decision.origen})
        logger.info("Cita #%s: decision=%s (%s)", cita["id"], decision.tipo, decision.origen)

        if decision.tipo in ("rechazar", "modificar") and decision.nueva_fecha_hora is None \
                and _SIN_ESPACIO.search(_sin_tildes(texto)):
            return self._pedir_otro_horario(cita, decision, texto, ahora or reloj())
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
        registrar_consulta(self.repo, self.propietaria, msg_id, cliente, pregunta)

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
        if _DECISION_CITA.search(_sin_tildes(texto)) and (self.repo.citas_por_estado("pendiente_aprobacion")
                                                          or self.repo.citas_por_estado("propuesta_cliente")):
            return None
        consulta = consultas.pop(msg_id)
        if sesion.get("ultima_consulta") == msg_id:
            sesion["ultima_consulta"] = None
        self.repo.guardar_sesion(self.propietaria, sesion)
        # Sale tal cual, en nombre del salon (propietaria, 18-oct: sin "la propietaria dice").
        self.mensajero.enviar(consulta["cliente"], texto)
        return f"📨 Se lo envié al cliente {consulta['cliente']} (preguntó: \"{consulta['pregunta']}\")."

    def _listar_pendientes(self) -> str:
        pendientes = self.repo.citas_por_estado("pendiente_aprobacion")
        if not pendientes:
            return "No tienes citas pendientes de aprobación 🙂"
        return "Pendientes:\n" + "\n".join(
            f"#{c['id']} — {mensajes.fecha_legible(c['fecha_hora'])} — "
            f"{', '.join(m.get('nombre') or 'mascota' for m in c['mascotas'])}" for c in pendientes)

    # -- cobro real (SCRUM-95) -------------------------------------------------

    def _sin_cobro(self, hasta: datetime) -> list[dict]:
        """Citas confirmadas de hoy o antes que aun no tienen el cobro registrado."""
        fin_del_dia = hasta.replace(hour=23, minute=59)
        return [c for c in self.repo.citas_por_estado("confirmada")
                if c.get("total_cobrado") is None and c.get("fecha_hora")
                and datetime.fromisoformat(c["fecha_hora"]) <= fin_del_dia]

    def _listar_por_cobrar(self, ahora: datetime) -> str:
        citas = self._sin_cobro(ahora)
        if not citas:
            return "No hay citas atendidas sin el cobro registrado 🙌"
        return ("Sin cobro registrado:\n" + "\n".join(
            f"#{c['id']} — {mensajes.fecha_legible(c['fecha_hora'])} — "
            f"{', '.join(m.get('nombre') or 'mascota' for m in c['mascotas'])} (cotizado {mensajes.texto_total(c)})"
            for c in citas) + "\n\nEscríbeme por ejemplo: \"cobré 22 a la cita #5\".")

    def _registrar_cobro(self, monto: float, numero: int | None, id_citado: str | None,
                         ahora: datetime) -> str:
        cita = None
        if numero is not None:
            cita = self.repo.obtener_cita(numero)
            if not cita:
                return f"No encontré la cita #{numero}."
        elif id_citado:
            cita = self.repo.cita_por_mensaje_aprobacion(id_citado)
        if cita is None:
            candidatas = self._sin_cobro(ahora)
            if len(candidatas) != 1:
                return ("¿A qué cita corresponde? Escríbeme el número, por ejemplo \"cobré "
                        f"{monto:g} a la cita #5\" (o responde \"por cobrar\" para ver la lista).")
            cita = candidatas[0]
        if cita["estado"] != "confirmada":
            return f"La cita #{cita['id']} no está confirmada ({cita['estado'].replace('_', ' ')}); no registré el cobro."

        anterior = cita.get("total_cobrado")
        self.repo.actualizar_cita(cita["id"], total_cobrado=monto, fecha_cobro=ahora)
        self.repo.registrar_evento(cita["id"], "cobrada", {
            "total_cobrado": monto, "cotizado": mensajes.texto_total(cita), "anterior": anterior})
        logger.info("Cita #%s: cobro registrado %.2f (cotizado %s)", cita["id"], monto, mensajes.texto_total(cita))
        correccion = f" (corregido; antes {anterior:.2f}$)" if anterior is not None else ""
        return (f"💰 Cita #{cita['id']}: registré {monto:.2f}$ cobrado{correccion}. "
                f"Se había cotizado {mensajes.texto_total(cita)}.")

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

    def _corregir_tamano(self, cita: dict, palabra: str) -> dict:
        tamano = _TAMANO_MOTOR[palabra[:3]]
        mascotas = [{**m, "tamano": tamano} for m in cita["mascotas"]]
        motor = [{k: m[k] for k in ("nombre", "servicio", "raza", "tamano", "grupo", "estado", "comportamiento")
                  if m.get(k) is not None} for m in mascotas]
        cotizacion = self.cotizador.cotizar(motor, cita["modalidad"], cita.get("sector"))
        self.repo.actualizar_cita(cita["id"], mascotas=mascotas, cotizacion=cotizacion)
        self.repo.registrar_evento(cita["id"], "tamano_corregido", {"tamano": tamano, "palabra": palabra,
                                                                    "total": cotizacion.get("total")})
        return self.repo.obtener_cita(cita["id"])

    def _pedir_otro_horario(self, cita: dict, d: Decision, texto: str, ahora: datetime) -> str:
        """No puede en ese horario: la misma cita se reabre y el cliente elige otro."""
        from app.agenda.disponibilidad import ocupado_combinado

        inicio = datetime.fromisoformat(cita["fecha_hora"])
        todo_el_dia = bool(_TODO_EL_DIA.search(_sin_tildes(texto)))
        desde = (inicio + timedelta(days=1)).replace(hour=0, minute=0) if todo_el_dia else inicio
        cambios: dict = {"estado": "en_reprogramacion", "ciclo_aprobacion": cita.get("ciclo_aprobacion", 1) + 1}
        if d.nuevo_total is not None:
            cambios["total_acordado"] = float(d.nuevo_total)
        self.repo.actualizar_cita(cita["id"], **cambios)
        self.repo.registrar_evento(cita["id"], "propietaria_pide_otro_horario",
                                   {"todo_el_dia": todo_el_dia, "nuevo_total": d.nuevo_total, "motivo": d.motivo})
        actualizada = self.repo.obtener_cita(cita["id"])
        duracion = (cita.get("cotizacion") or {}).get("duracion_agenda_min", 60)
        alternativas = proponer_alternativas(desde, duracion, cita["modalidad"], self.cotizador, self.cfg,
                                             ocupado_combinado(self.repo, self.calendario), ahora)
        self.mensajero.enviar(cita["cliente_telefono"],
                              mensajes.otro_horario_cliente(actualizada, alternativas, todo_el_dia))
        # El cliente sigue en el flujo de agenda con la misma cita: solo elige el horario.
        sesion = self.repo.obtener_sesion(cita["cliente_telefono"])
        sesion.update(
            flujo="agendando", cita_en_aprobacion=None, propuesta_cita=None, reprogramar_cita_id=cita["id"],
            preguntado=_TODO_PREGUNTADO, alternativas=[a.isoformat() for a in alternativas],
            reserva={"mascotas": cita["mascotas"], "fecha_hora": None, "modalidad": cita["modalidad"],
                     "sector": cita.get("sector"), "cliente_nombre": cita.get("cliente_nombre"),
                     "pedido_especial": cita.get("pedido_especial")},
        )
        self.repo.guardar_sesion(cita["cliente_telefono"], sesion)
        precio = f" con el total de {mensajes.texto_total(actualizada)}" if d.nuevo_total is not None else ""
        ofrecidos = ", ".join(mensajes.fecha_legible(a) for a in alternativas) or "ninguno (le pedí otro día)"
        return (f"📨 Le pedí al cliente otro horario para la cita #{cita['id']}{precio}. Le ofrecí: {ofrecidos}. "
                "Cuando elija, te la mando para aprobar.")

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
