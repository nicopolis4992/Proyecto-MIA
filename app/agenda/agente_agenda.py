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

Despues de crear la cita, la conversacion sigue viva:
- si la propietaria cambio hora o precio, el cliente acepta o pide otro horario;
- con una cita confirmada, el cliente puede reprogramarla o cancelarla
  ("a esa hora ya no puedo"), y la propietaria recibe el aviso;
- "¿que horarios tiene el martes?" se responde con horarios libres reales,
  sin inventar una hora.

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
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, time

from google.genai import types

from app.agenda import mensajes
from app.agenda.calendario import quitar_del_calendario, registrar_en_calendario
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
am/pm se interpretan entre 08:00 y 19:59. Si la clienta da el DIA pero NO la
hora, NO inventes una hora: deja fecha_hora en null y pon el dia en
dia_consultado.
dia_consultado: "YYYY-MM-DD" si pregunta que horarios hay un dia ("¿el lunes
a que hora tiene?", "¿que horarios tiene el martes 6?") o da un dia sin hora.
franja_preferida: "manana" o "tarde" si pide una parte del dia ("en la tarde",
"por la manana", "despues del almuerzo" = tarde). Null si no lo dice.
hora_minima: "HH:MM" si pide "despues de las X" o "desde las X" (ej. "despues
de las 3" = "15:00"). Null si no lo dice.

pedido_especial: si pide un cambio a lo que incluye el servicio ("sin baño
medicado", "sin accesorio", "solo corte de uñas", "que no le corten el pelo"),
descríbelo en pocas palabras, junto con lo que ya estaba en la reserva. Null si no.
pregunta_precio: true si pregunta cuánto cuesta o cuánto le baja con ese cambio.

accion_cita (solo si hay CITA EXISTENTE):
  "aceptar_propuesta": acepta el cambio que propuso la propietaria ("si", "dale", "perfecto").
  "rechazar_propuesta": no le sirve el cambio propuesto.
  "reprogramar": quiere cambiar el dia u hora de su cita ("a esa hora no puedo",
     "¿se puede mas tarde?", "mejor el viernes").
  "cancelar_cita": ya no quiere la cita.
  "ninguna": cualquier otra cosa (agradecer, preguntar, agendar OTRA mascota).
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
            "dia_consultado": S(type=T.STRING, nullable=True),
            "franja_preferida": S(type=T.STRING, enum=["manana", "tarde"], nullable=True),
            "pedido_especial": S(type=T.STRING, nullable=True),
            "pregunta_precio": S(type=T.BOOLEAN),
            "hora_minima": S(type=T.STRING, nullable=True),
            "accion_cita": S(type=T.STRING, enum=["ninguna", "aceptar_propuesta", "rechazar_propuesta",
                                                  "reprogramar", "cancelar_cita"]),
        },
        required=["mascotas", "fecha_hora", "modalidad", "sector", "cliente_nombre",
                  "eligio_alternativa", "cancelar", "dia_consultado", "franja_preferida",
                  "hora_minima", "pedido_especial", "pregunta_precio", "accion_cita"],
    )


_ACEPTAR = {"si", "sí", "si dale", "dale", "ok", "listo", "perfecto", "de una", "esta bien", "si esta bien",
            "si me parece", "si perfecto", "claro", "👍"}
_ATRIBUTOS = ("tamano", "raza_o_grupo_manto", "estado_manto", "comportamiento")


def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^\w\s👍]", "", t).strip()


def _trae_datos_de_reserva(datos: dict) -> bool:
    """True si el mensaje aporta algo para una reserva (otra mascota, fecha, etc.)."""
    if datos.get("fecha_hora") or datos.get("dia_consultado") or datos.get("eligio_alternativa"):
        return True
    return any(m.get("servicio") or m.get("nombre") for m in datos.get("mascotas") or [])


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

    def extraer(self, mensaje: str, reserva: dict, alternativas: list[str], ahora: datetime,
                cita: dict | None = None) -> dict:
        opciones = "\n".join(f"{i}. {a}" for i, a in enumerate(alternativas, 1)) or "ninguna"
        existente = "ninguna"
        if cita:
            existente = (f"#{cita['id']} {mensajes.fecha_legible(cita['fecha_hora'])}, estado "
                         f"{cita['estado']}" + (" (la propietaria propuso este cambio y espera respuesta)"
                                                 if cita["estado"] == "propuesta_cliente" else ""))
        contenido = (
            f"FECHA ACTUAL: {mensajes.fecha_legible(ahora)} ({ahora.strftime('%Y-%m-%dT%H:%M')})\n"
            f"CITA EXISTENTE: {existente}\n"
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
        alternativas = sesion.get("alternativas") or []
        cita = self.cita_vigente(sesion, ahora)

        # Respuesta corta a una propuesta de la propietaria: sin LLM.
        if cita and cita["estado"] == "propuesta_cliente" and _normalizar(mensaje) in _ACEPTAR:
            return self._aceptar_propuesta(telefono, cita)

        datos = self.extraer(mensaje, sesion["reserva"], alternativas, ahora, cita)
        logger.info("Agenda | %s | extraido=%s", telefono, datos)
        accion = datos.get("accion_cita") or "ninguna"

        if cita and accion == "aceptar_propuesta" and cita["estado"] == "propuesta_cliente":
            return self._aceptar_propuesta(telefono, cita)
        if cita and accion == "cancelar_cita":
            return self._cancelar_cita(telefono, cita)
        if cita and accion in ("reprogramar", "rechazar_propuesta"):
            self._iniciar_reprogramacion(sesion, cita)
        elif cita and accion == "ninguna" and not sesion.get("reprogramar_cita_id") \
                and not _trae_datos_de_reserva(datos):
            # "gracias", "ok" tras confirmar: no se abre una reserva nueva.
            return self._estado_de_cita(cita)

        if datos.get("cancelar") and not sesion.get("reprogramar_cita_id"):
            self._terminar(telefono, sesion)
            return "Entendido, no agendo nada por ahora. Cuando guste me escribe 🐾"

        sesion["flujo"] = "agendando"
        reserva = self._fusionar(sesion["reserva"], datos)
        n = datos.get("eligio_alternativa")
        if n and 1 <= n <= len(alternativas):
            reserva["fecha_hora"] = alternativas[n - 1]
        sesion["reserva"] = reserva

        if datos.get("pedido_especial"):
            # El pedido se anota y la propietaria define el precio al aprobar.
            # El precio solo se menciona si el cliente lo pregunta.
            nota = f"Anoto su pedido: {datos['pedido_especial']}. La propietaria lo revisa con su cita"
            nota += " y le confirma el precio con ese cambio." if datos.get("pregunta_precio") else "."
            return f"{nota}\n\n{self.continuar(telefono, sesion, ahora)}"
        if datos.get("pregunta_precio") and reserva.get("pedido_especial"):
            return ("El precio con su pedido especial lo valida la propietaria; se lo confirmo al revisar "
                    "su cita. " + self.continuar(telefono, sesion, ahora))

        # La preferencia ("en la tarde", "despues de las 3") se recuerda para
        # todas las opciones que se ofrezcan en esta conversacion.
        for clave in ("franja_preferida", "hora_minima", "dia_consultado"):
            if datos.get(clave):
                sesion[clave] = datos[clave]
        pide_opciones = datos.get("dia_consultado") or datos.get("franja_preferida") or datos.get("hora_minima")
        if pide_opciones and not reserva.get("fecha_hora"):
            # "¿y en la tarde?" sin dia se refiere al dia que se estaba mirando.
            dia = datos.get("dia_consultado") or sesion.get("dia_consultado")
            return self._ofrecer_horarios_del_dia(telefono, sesion, dia, ahora, cita)
        if accion in ("reprogramar", "rechazar_propuesta") and not reserva.get("fecha_hora"):
            return self._ofrecer_horarios_del_dia(telefono, sesion, None, ahora, cita)
        return self.continuar(telefono, sesion, ahora)

    # -- citas existentes (propuestas, reprogramacion, cancelacion) ----------

    def cita_vigente(self, sesion: dict, ahora: datetime) -> dict | None:
        """La cita sobre la que el cliente puede actuar: propuesta, por aprobar o confirmada futura."""
        for clave in ("propuesta_cita", "cita_en_aprobacion", "reprogramar_cita_id", "cita_activa"):
            if sesion.get(clave):
                c = self.repo.obtener_cita(sesion[clave])
                if c and c["estado"] not in ("cancelada", "rechazada") and c.get("fecha_hora") \
                        and datetime.fromisoformat(c["fecha_hora"]) > ahora:
                    return c
        return None

    def _aceptar_propuesta(self, telefono: str, cita: dict) -> str:
        self.repo.actualizar_cita(cita["id"], estado="confirmada")
        self.repo.registrar_evento(cita["id"], "cliente_acepto_propuesta")
        self.repo.registrar_evento(cita["id"], "confirmada", {"origen": "propuesta aceptada por el cliente"})
        cita = self.repo.obtener_cita(cita["id"])
        extra = registrar_en_calendario(self.repo, self.calendario, cita)
        self._avisar_propietaria(f"✅ El cliente aceptó el cambio: cita #{cita['id']} confirmada para el "
                                 f"{mensajes.fecha_legible(cita['fecha_hora'])}.{extra}")
        self.repo.guardar_sesion(telefono, {"cita_activa": cita["id"]})
        return mensajes.confirmacion_cliente(cita)

    def _cancelar_cita(self, telefono: str, cita: dict) -> str:
        self.repo.actualizar_cita(cita["id"], estado="cancelada")
        self.repo.registrar_evento(cita["id"], "cancelada_por_cliente")
        quitar_del_calendario(self.repo, self.calendario, cita["id"])
        self._avisar_propietaria(f"❌ El cliente canceló la cita #{cita['id']} del "
                                 f"{mensajes.fecha_legible(cita['fecha_hora'])}. El horario quedó libre.")
        self.repo.guardar_sesion(telefono, {})
        return "Listo, cancelé su cita. Cuando quiera agendar de nuevo, aquí estoy 🐾"

    def _iniciar_reprogramacion(self, sesion: dict, cita: dict) -> None:
        """Reabre la reserva con los datos de la cita, menos el horario."""
        if sesion.get("reprogramar_cita_id") == cita["id"]:
            return
        estaba_confirmada = cita["estado"] == "confirmada"
        self.repo.actualizar_cita(cita["id"], estado="en_reprogramacion")
        self.repo.registrar_evento(cita["id"], "cliente_pide_reprogramar", {"estado_previo": cita["estado"]})
        if estaba_confirmada:
            quitar_del_calendario(self.repo, self.calendario, cita["id"])
        self._avisar_propietaria(f"🔁 El cliente pidió cambiar el horario de la cita #{cita['id']} "
                                 f"({mensajes.fecha_legible(cita['fecha_hora'])}). Le estoy ofreciendo "
                                 "otros horarios; te mando la nueva propuesta para aprobar.")
        sesion.clear()
        sesion.update(
            flujo="agendando", reprogramar_cita_id=cita["id"], preguntado=list(_ATRIBUTOS),
            reserva={"mascotas": cita["mascotas"], "fecha_hora": None, "modalidad": cita["modalidad"],
                     "sector": cita.get("sector"), "cliente_nombre": cita.get("cliente_nombre"),
                     "pedido_especial": cita.get("pedido_especial")},
        )

    def _ofrecer_horarios_del_dia(self, telefono: str, sesion: dict, dia: str | None, ahora: datetime,
                                  cita: dict | None = None) -> str:
        r = sesion["reserva"]
        cot = self.cotizador.cotizar(para_motor(r["mascotas"]), r.get("modalidad") or "salon", r.get("sector")) \
            if r["mascotas"] and all(m.get("servicio") for m in r["mascotas"]) else None
        duracion = cot["duracion_agenda_min"] if cot else 60
        if dia:
            desde = datetime.fromisoformat(dia).replace(hour=0, tzinfo=ZONA_HORARIA)
        elif cita:
            desde = datetime.fromisoformat(cita["fecha_hora"])
        else:
            desde = ahora
        ocupado = ocupado_combinado(self.repo, self.calendario)
        alternativas = proponer_alternativas(desde, duracion, r.get("modalidad") or "salon", self.cotizador,
                                             self.cfg, ocupado, ahora, **self._preferencia(sesion))
        sesion["alternativas"] = [a.isoformat() for a in alternativas]
        self.repo.guardar_sesion(telefono, sesion)
        if not alternativas:
            return "No encuentro horarios libres en esos días 😕 ¿Qué otro día le queda bien?"
        opciones = "\n".join(f"{i}. {mensajes.fecha_legible(a)}" for i, a in enumerate(alternativas, 1))
        if dia is None and cita:
            inicio = "Sin problema, busquemos otro horario. Le puedo ofrecer:"
        elif dia is None:
            inicio = "Estos son los horarios más cercanos que tengo:"
        elif all(a.date().isoformat() == dia for a in alternativas):
            inicio = "Para ese día tengo libre:"
        elif alternativas[0].date().isoformat() == dia:
            inicio = "Tengo libre:"
        else:
            inicio = "Ese día no me queda espacio; lo más cercano es:"
        return f"{inicio}\n{opciones}\nRespóndame con el número de la opción o indíqueme otra hora."

    def _mencionar_precio_pedido(self) -> bool:
        return bool(self.cfg.get("pedidos_especiales", {}).get("mencionar_precio_al_cliente"))

    @staticmethod
    def _preferencia(sesion: dict) -> dict:
        pref: dict = {}
        if sesion.get("franja_preferida") in ("manana", "tarde"):
            pref["franja"] = sesion["franja_preferida"]
        if sesion.get("hora_minima"):
            try:
                pref["hora_minima"] = time.fromisoformat(sesion["hora_minima"])
            except ValueError:
                pass
        return pref

    def _estado_de_cita(self, cita: dict) -> str:
        if cita["estado"] == "propuesta_cliente":
            return (f"La propietaria le propuso el {mensajes.fecha_legible(cita['fecha_hora'])} "
                    f"({mensajes.texto_total(cita)}). ¿Le parece bien? Respóndame \"sí\" o dígame otro horario.")
        if cita["estado"] == "pendiente_aprobacion":
            return "Su cita está en revisión; le confirmo apenas la propietaria la apruebe 🙌"
        return (f"¡Con gusto! Su cita sigue para el {mensajes.fecha_legible(cita['fecha_hora'])}. "
                "Si necesita cambiarla o cancelarla, solo dígamelo 🐾")

    def _avisar_propietaria(self, texto: str) -> None:
        if self.propietaria:
            self.mensajero.enviar(self.propietaria, texto)

    def continuar(self, telefono: str, sesion: dict, ahora: datetime) -> str:
        """Decide el siguiente paso con la reserva actual (tambien tras una foto)."""
        pregunta = self.siguiente_pregunta(sesion)
        if pregunta:
            self.repo.guardar_sesion(telefono, sesion)
            return pregunta
        return self._cerrar_reserva(telefono, sesion, ahora)

    def _fusionar(self, anterior: dict, nuevo: dict) -> dict:
        r = dict(anterior)
        for campo in ("fecha_hora", "modalidad", "sector", "cliente_nombre", "pedido_especial"):
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
        self.repo.guardar_sesion(telefono, {k: v for k, v in sesion.items()
                                            if k in ("cita_en_aprobacion", "propuesta_cita", "cita_activa")})

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
                                                 ocupado, ahora, **self._preferencia(sesion))
            sesion["alternativas"] = [a.isoformat() for a in alternativas]
            r["fecha_hora"] = None
            self.repo.guardar_sesion(telefono, sesion)
            return mensajes.reprogramacion_cliente({"fecha_hora": inicio.isoformat()}, alternativas, motivo)

        reprogramada = sesion.get("reprogramar_cita_id")
        if reprogramada:
            previa = self.repo.obtener_cita(reprogramada)
            self.repo.actualizar_cita(
                # Solo cambia el horario: el precio que ya acordo la propietaria se mantiene.
                reprogramada, fecha_hora=inicio, cotizacion=cotizacion, estado="pendiente_aprobacion",
                ciclo_aprobacion=(previa or {}).get("ciclo_aprobacion", 1) + 1)
            self.repo.registrar_evento(reprogramada, "nuevo_horario_elegido", {"fecha_hora": inicio})
            cita_id = reprogramada
        else:
            cita_id = self.repo.crear_cita(
                cliente_telefono=telefono, cliente_nombre=r.get("cliente_nombre"),
                pedido_especial=r.get("pedido_especial"),
                mascotas=r["mascotas"], fecha_hora=inicio, modalidad=r["modalidad"],
                zona=(cotizacion.get("traslado") or {}).get("zona"), sector=r.get("sector"),
                cotizacion=cotizacion, requiere_revision_manual=bool(sesion.get("revision_manual")),
            )
        if sesion.get("traza_foto"):
            self.repo.registrar_evento(cita_id, "cotizacion_por_foto", sesion["traza_foto"])
        cita = self.repo.obtener_cita(cita_id)
        if self.propietaria:
            encabezado = f"🔁 Cita #{cita_id} reprogramada por el cliente: aprobar nuevo horario" if reprogramada else None
            msg_id = self.mensajero.enviar(self.propietaria, mensajes.resumen_para_propietaria(cita, encabezado))
            self.repo.actualizar_cita(cita_id, msg_aprobacion_id=msg_id)
            self.repo.registrar_evento(cita_id, "enviada_a_propietaria", {"wa_id": msg_id})
        else:
            logger.error("PROPIETARIA_WHATSAPP no configurado: la cita #%s no se envio a aprobar", cita_id)

        self.repo.guardar_sesion(telefono, {"cita_en_aprobacion": cita_id})
        valor = cotizacion["mensaje_cliente"]
        if r.get("pedido_especial") and not self._mencionar_precio_pedido():
            valor = "El precio con su pedido especial se lo confirma la propietaria."
        return (f"¡Perfecto! Tengo todo para el {mensajes.fecha_legible(inicio)}. "
                f"{valor} Le confirmo en un momento, apenas se revise la agenda 🙌")
