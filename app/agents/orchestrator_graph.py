"""
orchestrator_graph.py

Cubre:
- SCRUM-65: Integrar el agente NLU con el orquestador multiagente
- Integracion del prototipo (S4): reemplaza los stubs de RAG y Agenda por
  los agentes reales y agrega dos entradas que no pasan por el NLU:
    * mensajes de la propietaria -> procesador de aprobacion (SCRUM-77/78)
    * fotos -> cotizacion por imagen (SCRUM-103/104)

Flujo:
    START --(propietaria)--> aprobacion --> END
          --(bot en pausa)-> pausado (reenvio a la propietaria) --> END
          --(imagen)-------> cotizacion_imagen --> END
          --(texto)--------> nlu --consultar--> agente_rag --> END
                                 --agendar----> agente_agenda --> END
                                 --general----> agente_general --> END
                                   (general con una reserva en curso -> agente_agenda)

El estado de la conversacion entre mensajes (reserva a medio llenar, fotos
intentadas, cita en aprobacion) vive en el repositorio, indexado por numero
de WhatsApp; el grafo en si es sin estado.

Requiere: pip install langgraph google-genai
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

# El try/except permite que este archivo funcione de dos formas:
# - Como script suelto (python orchestrator_graph.py desde dentro de agents/)
# - Como parte del paquete app.agents cuando main.py lo importa
try:
    from .nlu_extractor import ResultadoNLU, clasificar_mensaje
except ImportError:
    from nlu_extractor import ResultadoNLU, clasificar_mensaje

from google.genai import types

from app.agenda import origen
from app.agenda.agente_agenda import AgenteAgenda, reserva_vacia
from app.agenda.aprobacion import ProcesadorAprobacion
from app.agenda.disponibilidad import cargar_config
from app.config import MODELO_LLM, PROPIETARIA_WHATSAPP, RUTA_TARIFARIO, ahora
from app.rag.agente_rag import RESPUESTA_SIN_CONTEXTO
from app.cotizacion.cotizador_imagen import cargar_politica, procesar_foto
from app.cotizacion.cotizador import Cotizador

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orquestador")

MENSAJE_ERROR = ("Disculpe, tuve un inconveniente técnico procesando su mensaje. "
                 "¿Me lo puede repetir en un momento? 🙏")


class EstadoConversacion(TypedDict, total=False):
    remitente: str
    mensaje: str
    imagen: bytes | None
    id_citado: str | None          # id del mensaje al que se responde (cita)
    nlu: ResultadoNLU | None
    en_flujo_agenda: bool
    respuesta: str | None


@dataclass
class Dependencias:
    client: object
    repo: object
    mensajero: object
    cotizador: Cotizador
    agente_rag: object
    agenda: AgenteAgenda
    aprobacion: ProcesadorAprobacion
    clasificador: object
    propietaria: str


# --- Enrutamiento ---

def enrutar_entrada(estado: EstadoConversacion, d: "Dependencias") -> Literal[
        "aprobacion", "cotizacion_imagen", "nlu", "agente_agenda", "pausado", "respuesta_fija"]:
    if d.propietaria and estado["remitente"] == d.propietaria:
        return "aprobacion"
    if d.repo.bot_pausado():
        return "pausado"
    # SCRUM-75: origen y referido se anotan al pasar, sin importar a que nodo vaya.
    origen.anotar(d.repo, estado["remitente"], estado.get("mensaje") or "")
    if estado.get("imagen"):
        return "cotizacion_imagen"
    if pregunta_ubicacion(estado["mensaje"]) or (
            pide_informacion_general(estado["mensaje"]) and not en_flujo_agenda(estado["remitente"], d)):
        return "respuesta_fija"
    # Ahorro de llamadas: en medio de una reserva, un mensaje que no es una
    # pregunta general ("se llama Toby", "el viernes", "sin accesorio") va
    # directo a la agenda, sin pasar por el clasificador de intencion.
    sesion = d.repo.obtener_sesion(estado["remitente"])
    if en_flujo_agenda(estado["remitente"], d) and (
            va_a_la_agenda(estado["mensaje"]) or precio_de_pedido_especial(estado["mensaje"], sesion)):
        logger.info("NLU omitido: mensaje dentro de una reserva")
        return "agente_agenda"
    return "nlu"


_PREGUNTA_PRECIO = re.compile(r"cu[aá]nto|precio|valor|cuesta|sale|saldr|cobr")


def precio_de_pedido_especial(texto: str, sesion: dict) -> bool:
    """Con un pedido especial anotado, el precio lo valida la propietaria (lo responde
    la agenda), no la tabla general de precios del RAG."""
    return bool((sesion.get("reserva") or {}).get("pedido_especial")) and bool(_PREGUNTA_PRECIO.search(texto.lower()))


def en_flujo_agenda(remitente: str, d: "Dependencias") -> bool:
    """Hay una reserva en curso o una cita sobre la que el cliente puede actuar."""
    sesion = d.repo.obtener_sesion(remitente)
    return sesion.get("flujo") == "agendando" or d.agenda.cita_vigente(sesion, ahora()) is not None


def va_a_la_agenda(texto: str) -> bool:
    return not parece_pregunta(texto) or pregunta_de_agenda(texto) or pedido_personalizado(texto)


# Sin "?" solo cuentan los inicios inequivocos. "que"/"como" sin tilde no:
# "que la recojan en mi casa" o "como le dije" son pedidos, no preguntas.
_INTERROGATIVOS = ("cuanto", "cuánto", "qué ", "cómo ", "donde", "dónde", "cuándo", "cuál",
                   "tienen", "hacen", "aceptan", "hay ")


def parece_pregunta(texto: str) -> bool:
    t = texto.strip().lower()
    return "?" in t or "¿" in t or t.startswith(_INTERROGATIVOS)


_SOBRE_AGENDA = re.compile(
    r"horario|disponib|libre|cupo|turno|espacio|agend|reprogram|cambiar|cancel|"
    r"\btarde\b|temprano|\ba las \d|despu[eé]s de las|antes de las|desde las|"
    r"\b(lunes|martes|miercoles|miércoles|jueves|viernes|sabado|sábado|domingo|hoy|mañana|manana)\b")


def pregunta_de_agenda(texto: str) -> bool:
    """Preguntas que responde la agenda (horarios libres), no la base de conocimiento."""
    return bool(_SOBRE_AGENDA.search(texto.lower()))


_PERSONALIZACION = re.compile(
    r"\bsin (el |la |los |las |un |una )?\w|\bquit|\bno (quiero|necesito|le (pongan|pongas|hagan|ponga))|"
    r"\bsolo (el|la|quiero|corte|ba[nñ]o|u[nñ]as)|\bmenos el\b|\bpersonaliz|\ben vez de\b")


def pedido_personalizado(texto: str) -> bool:
    """Cambios a lo que incluye un servicio: los anota la agenda (pedido especial)."""
    return bool(_PERSONALIZACION.search(texto.lower()))


# "Quiero un baño completo para Fara" pide el servicio (agendar), aunque el NLU
# lo lea como "consultar" por mencionar un servicio. Prueba del 17-oct: sin
# esto la reserva nunca empezaba y el RAG respondia precios.
_PIDE_SERVICIO = re.compile(
    r"\b(quiero|quisiera|necesito|me gustar[ií]a|deseo|quer[ií]a)\b.{0,40}"
    r"\b(ba[nñ]o|corte|peluquer[ií]a|servicio|deslanad|cita|turno|agendar)")


def pide_servicio(texto: str) -> bool:
    return not parece_pregunta(texto) and bool(_PIDE_SERVICIO.search(texto.lower()))


# Prueba del 18-oct: "encontre este lugar en instagram y quiero saber mas
# informacion" iba al RAG, que no encontraba nada concreto y lo pasaba a la
# propietaria. Una pregunta general se responde con la presentacion del salon.
_INFO_GENERAL = re.compile(r"\b(m[aá]s )?informaci[oó]n\b|\binfo\b|qu[eé] (servicios|hacen|ofrecen)|"
                           r"c[oó]mo funciona|de qu[eé] se trata")
_TEMA_CONCRETO = re.compile(r"precio|cu[aá]nto|cuest|vale|ba[nñ]o|corte|cita|agend|horario|puerta|"
                            r"domicilio|pago|tarjeta|factura|hospedaje|snack")
_UBICACION = re.compile(r"d[oó]nde (queda|quedan|est[aá]n?|se ubica|se encuentra|los encuentro|es el local)|"
                        r"\bubicaci[oó]n\b|\bdirecci[oó]n\b|c[oó]mo llego|\bel local\b.*\bd[oó]nde\b")


def pide_informacion_general(texto: str) -> bool:
    t = texto.lower()
    return bool(_INFO_GENERAL.search(t)) and not _TEMA_CONCRETO.search(t)


def pregunta_ubicacion(texto: str) -> bool:
    return bool(_UBICACION.search(texto.lower()))


def enrutar_por_intencion(
    estado: EstadoConversacion,
) -> Literal["agente_rag", "agente_agenda", "agente_general"]:
    intencion = estado["nlu"].intencion

    # Con una reserva en curso, describir a la mascota ("su pelo le crece y
    # hay que cortarlo") suena a "consultar" para el NLU, pero es la respuesta
    # a una pregunta del agente de agenda. Solo una pregunta explicita va al RAG.
    if intencion == "consultar" and estado.get("en_flujo_agenda") and va_a_la_agenda(estado["mensaje"]):
        return "agente_agenda"
    if intencion == "consultar" and pide_servicio(estado["mensaje"]):
        return "agente_agenda"
    if intencion == "consultar":
        return "agente_rag"
    if intencion == "agendar":
        return "agente_agenda"
    # Un "general" en medio de una reserva suele ser la respuesta a una
    # pregunta del agente de agenda ("se llama Toby", "el viernes"). Pero una
    # PREGUNTA general ("¿aceptan tarjeta?") va al agente general, que la
    # releva a la propietaria; si fuera a la agenda, se perderia.
    if estado.get("en_flujo_agenda") and va_a_la_agenda(estado["mensaje"]):
        return "agente_agenda"
    # "general" y cualquier caso no reconocido caen aqui como fallback seguro
    return "agente_general"


# --- Nodos ---

def nodo_nlu(estado: EstadoConversacion, d: Dependencias) -> EstadoConversacion:
    estado["nlu"] = clasificar_mensaje(estado["mensaje"], d.client)
    # La agenda sigue a cargo si hay una reserva en curso o una cita sobre la
    # que el cliente puede actuar (propuesta, por aprobar o confirmada futura).
    estado["en_flujo_agenda"] = en_flujo_agenda(estado["remitente"], d)
    return estado


def nodo_rag(estado: EstadoConversacion, d: Dependencias) -> EstadoConversacion:
    r = d.agente_rag(estado["mensaje"])
    estado["respuesta"] = r.texto
    if not r.fundamentada:
        # El cliente recibio "le comento a la propietaria": hay que hacerlo.
        _reenviar_a_propietaria(estado, d)
    logger.info("Enrutado a agente_rag (fundamentada=%s)", r.fundamentada)
    return estado


def _reenviar_a_propietaria(estado: EstadoConversacion, d: Dependencias) -> None:
    """Pregunta que el bot no puede responder: se la pasa a la propietaria (relevo)."""
    if not d.propietaria:
        return
    msg_id = d.mensajero.enviar(
        d.propietaria, f"❓ Pregunta sin respuesta de {estado['remitente']}: \"{estado['mensaje']}\"\n"
                       "Respóndeme citando este mensaje y se lo envío al cliente.")
    d.aprobacion.registrar_consulta(msg_id, estado["remitente"], estado["mensaje"])


# Lo que agrega cada servicio (son acumulativos), para una lectura rapida en WhatsApp.
RESUMEN_SERVICIO = {
    "express": "baño, secado, perfume y accesorios",
    "basico": "lo del Express más corte de la zona lagrimal y despeje de la zona genital",
    "completo": "lo del Básico más corte o peinado, uñas, oídos e hidratación de almohadillas",
    "premium": "lo del Completo más baño medicado y antipulgas",
}


def presentacion(cotizador: Cotizador) -> str:
    """Respuesta a "quiero más información": qué es el salón y sus servicios (del tarifario)."""
    servicios = "\n".join(f"• {s['nombre']}: {RESUMEN_SERVICIO.get(codigo, ', '.join(s['incluye']))} "
                          f"(desde ${s['piso']:g})" for codigo, s in cotizador.datos["servicios"].items())
    return ("¡Hola! Qué gusto saludarle 🐾 Somos Lina's Pet Salón, peluquería canina en Quito. "
            f"Atendemos perritos de todos los tamaños, de raza y mestizos. Nuestros servicios:\n{servicios}\n\n"
            "El precio exacto depende del tamaño, el tipo de pelo y el estado de su perrito. "
            "¿Le gustaría agendar una cita o saber el precio para su perrito?")


def nodo_respuesta_fija(estado: EstadoConversacion, d: Dependencias) -> EstadoConversacion:
    """Ubicacion del local (pin de WhatsApp) y presentacion del salon, sin LLM."""
    if not pregunta_ubicacion(estado["mensaje"]):
        estado["respuesta"] = presentacion(d.cotizador)
        return estado
    ubicacion = cargar_config().get("ubicacion_local") or {}
    if ubicacion.get("latitud") is None or ubicacion.get("longitud") is None:
        # Aun sin coordenadas: se le pasa a la propietaria, como cualquier pregunta sin respuesta.
        estado["respuesta"] = RESPUESTA_SIN_CONTEXTO
        _reenviar_a_propietaria(estado, d)
        return estado
    d.mensajero.enviar_ubicacion(estado["remitente"], ubicacion)
    texto = "Aquí le comparto nuestra ubicación 📍"
    if ubicacion.get("enlace_maps"):
        texto += f"\nEn Google Maps: {ubicacion['enlace_maps']}"
    sesion = d.repo.obtener_sesion(estado["remitente"])
    if en_flujo_agenda(estado["remitente"], d) and sesion.get("ultima_pregunta"):
        texto += f"\n\n{sesion['ultima_pregunta']}"  # sigue la reserva donde iba
    estado["respuesta"] = texto
    logger.info("Respuesta fija: ubicacion del local")
    return estado


def nodo_pausado(estado: EstadoConversacion, d: Dependencias) -> EstadoConversacion:
    """Bot en pausa (plan de contingencia): el mensaje va tal cual a la propietaria,
    sin LLM, y su respuesta citada vuelve al cliente por el relevo de consultas."""
    texto = estado.get("mensaje") or ""
    if estado.get("imagen"):
        texto = (texto + " [envió una foto: pídele que te la mande a tu número]").strip()
    if d.propietaria:
        msg_id = d.mensajero.enviar(
            d.propietaria, f"💬 (bot en pausa) {estado['remitente']}: \"{texto}\"\n"
                           "Respóndeme citando este mensaje y se lo envío.")
        d.aprobacion.registrar_consulta(msg_id, estado["remitente"], texto)
    estado["respuesta"] = None
    logger.info("Bot en pausa: mensaje de %s reenviado a la propietaria", estado["remitente"])
    return estado


def nodo_agenda(estado: EstadoConversacion, d: Dependencias) -> EstadoConversacion:
    estado["respuesta"] = d.agenda.atender(estado["remitente"], estado["mensaje"], ahora())
    if estado["respuesta"] is None:
        # Pregunta que no es de la agenda ("¿que es el baño premium?"): la responde la base de
        # conocimiento y, si hay una reserva en curso, se repite la pregunta pendiente.
        logger.info("Agenda sin respuesta: pregunta para el RAG")
        nodo_rag(estado, d)
        sesion = d.repo.obtener_sesion(estado["remitente"])
        if sesion.get("flujo") == "agendando" and sesion.get("ultima_pregunta"):
            estado["respuesta"] = f"{estado['respuesta']}\n\n{sesion['ultima_pregunta']}"
        return estado
    logger.info("Enrutado a agente_agenda")
    return estado


PROMPT_GENERAL = """Eres el asistente de WhatsApp de Lina's Pet Salón, peluquería
canina en Quito. Respondes saludos, agradecimientos y mensajes generales con
calidez y brevedad (1-2 líneas, en español de Ecuador, tratando de "usted").
No des precios, horarios ni datos del negocio: si preguntan algo así, invita a
consultarlo o a enviar una foto de su perrito para cotizar. Si el mensaje no
tiene relación con el negocio, redirige amablemente.

Si el cliente hace una pregunta CONCRETA sobre el negocio que tú no puedes
saber (medios de pago, factura, a qué hora recoger, qué llevar, dónde queda,
hasta dónde llega el servicio), NO la respondas ni inventes: responde
exactamente CONSULTAR_PROPIETARIA y nada más."""
MARCA_CONSULTA = "CONSULTAR_PROPIETARIA"


def nodo_general(estado: EstadoConversacion, d: Dependencias) -> EstadoConversacion:
    response = d.client.models.generate_content(
        model=MODELO_LLM, contents=estado["mensaje"],
        config=types.GenerateContentConfig(system_instruction=PROMPT_GENERAL, temperature=0.6),
    )
    texto = response.text.strip()
    if MARCA_CONSULTA in texto:
        # Pregunta concreta del negocio (con el NLU v2, pagos y logistica
        # llegan aqui). Primero la base de conocimiento: si la sabe
        # (p. ej. "¿como se paga?"), responde; si no, se releva a la propietaria.
        r = d.agente_rag(estado["mensaje"])
        texto = r.texto
        if not r.fundamentada:
            _reenviar_a_propietaria(estado, d)
    estado["respuesta"] = texto
    logger.info("Enrutado a agente_general")
    return estado


def nodo_aprobacion(estado: EstadoConversacion, d: Dependencias) -> EstadoConversacion:
    estado["respuesta"] = d.aprobacion.procesar(estado["mensaje"], estado.get("id_citado"), ahora())
    logger.info("Enrutado a aprobacion (propietaria)")
    return estado


def nodo_cotizacion_imagen(estado: EstadoConversacion, d: Dependencias) -> EstadoConversacion:
    tel = estado["remitente"]
    sesion = d.repo.obtener_sesion(tel)
    ya_agendando = sesion.get("flujo") == "agendando"
    reserva = sesion.setdefault("reserva", reserva_vacia())
    mascotas = reserva["mascotas"] or [{}]
    idx = next((i for i, m in enumerate(mascotas) if not m.get("tamano")), 0)
    m = mascotas[idx]

    intento = sesion.get("fotos_intentos", 0) + 1
    # Sin servicio elegido se muestra todo el catalogo.
    servicios = [m["servicio"]] if m.get("servicio") else None
    base = {k: v for k, v in m.items() if k != "servicio" and v is not None}
    r = procesar_foto(estado["imagen"], d.clasificador, d.cotizador, intento, servicios, base)

    if r.accion == "pedir_otra_foto":
        sesion["fotos_intentos"] = intento
        d.repo.guardar_sesion(tel, sesion)
        estado["respuesta"] = r.mensaje
        return estado

    for k, v in r.atributos.items():
        if not m.get(k):  # lo declarado por la clienta no se pisa
            m[k] = v
    mascotas[idx] = m
    reserva["mascotas"] = mascotas
    sesion.update(fotos_intentos=0, flujo="agendando", traza_foto=r.traza,
                  revision_manual=sesion.get("revision_manual") or r.revision_manual)
    # Ya se intento con foto: no se vuelve a pedir el tamano por texto.
    sesion.setdefault("preguntado", []).append("tamano")

    mensaje = r.mensaje
    politica = cargar_politica().get("foto_a_la_propietaria", {})
    if politica.get("activo"):
        # Propietaria, 18-oct: la foto le llega JUNTO con la solicitud de la cita
        # (agente_agenda._cerrar_reserva), con lo que vio el sistema y el precio.
        fotos = sesion.setdefault("fotos", [])
        fotos.append(base64.b64encode(estado["imagen"]).decode())
        sesion["fotos"] = fotos[-2:]
        if not politica.get("rango_al_cliente", True):
            mensaje = "¡Gracias por la foto! 🐾"

    if ya_agendando:
        cierre = d.agenda.continuar(tel, sesion, ahora())
    else:
        d.repo.guardar_sesion(tel, sesion)
        cierre = "¿Le gustaría agendar una cita? 🐾"
    estado["respuesta"] = f"{mensaje}\n\n{cierre}"
    logger.info("Enrutado a cotizacion_imagen (%s)", r.traza.get("decision"))
    return estado


def construir_grafo(d: Dependencias):
    grafo = StateGraph(EstadoConversacion)

    grafo.add_node("nlu", lambda e: nodo_nlu(e, d))
    grafo.add_node("agente_rag", lambda e: nodo_rag(e, d))
    grafo.add_node("agente_agenda", lambda e: nodo_agenda(e, d))
    grafo.add_node("agente_general", lambda e: nodo_general(e, d))
    grafo.add_node("aprobacion", lambda e: nodo_aprobacion(e, d))
    grafo.add_node("cotizacion_imagen", lambda e: nodo_cotizacion_imagen(e, d))
    grafo.add_node("pausado", lambda e: nodo_pausado(e, d))
    grafo.add_node("respuesta_fija", lambda e: nodo_respuesta_fija(e, d))

    grafo.add_conditional_edges(
        START,
        lambda e: enrutar_entrada(e, d),
        {"aprobacion": "aprobacion", "cotizacion_imagen": "cotizacion_imagen", "nlu": "nlu",
         "agente_agenda": "agente_agenda", "pausado": "pausado", "respuesta_fija": "respuesta_fija"},
    )
    # Este es el reemplazo real del "un solo nodo" de SCRUM-85: en lugar de
    # un edge fijo, add_conditional_edges decide el siguiente nodo en
    # tiempo de ejecucion segun la intencion detectada por el NLU.
    grafo.add_conditional_edges(
        "nlu",
        enrutar_por_intencion,
        {
            "agente_rag": "agente_rag",
            "agente_agenda": "agente_agenda",
            "agente_general": "agente_general",
        },
    )
    for nodo in ("agente_rag", "agente_agenda", "agente_general", "aprobacion", "cotizacion_imagen", "pausado",
                 "respuesta_fija"):
        grafo.add_edge(nodo, END)

    return grafo.compile()


def crear_dependencias(client=None, repo=None, mensajero=None, propietaria: str | None = None,
                       agente_rag=None, clasificador=None, calendario=None) -> Dependencias:
    """`calendario=False` desactiva Google Calendar (simulador, pruebas)."""
    from app.agenda.calendario import crear_calendario
    from app.config import crear_cliente_gemini
    from app.mensajeria import MensajeroWhatsApp
    from app.persistencia.repositorio import obtener_repositorio
    from app.rag.agente_rag import crear_agente_rag
    from app.vision.clasificador import crear_clasificador

    client = client or crear_cliente_gemini()
    repo = repo or obtener_repositorio()
    mensajero = mensajero or MensajeroWhatsApp(repo)
    propietaria = PROPIETARIA_WHATSAPP if propietaria is None else propietaria
    cotizador = Cotizador(RUTA_TARIFARIO)
    if calendario is None:
        calendario = crear_calendario()
    elif calendario is False:
        calendario = None
    cfg = cargar_config()
    return Dependencias(
        client=client, repo=repo, mensajero=mensajero, cotizador=cotizador,
        agente_rag=agente_rag or crear_agente_rag(client),
        agenda=AgenteAgenda(client, repo, mensajero, cotizador, cfg, propietaria, calendario),
        aprobacion=ProcesadorAprobacion(client, repo, mensajero, cotizador, cfg, propietaria, calendario),
        clasificador=clasificador or crear_clasificador(client),
        propietaria=propietaria,
    )


# --- Instancia compartida para uso en produccion (via app/agent.py) ---
# Se crea una sola vez, en el primer mensaje (no al importar, para que las
# pruebas y el arranque de FastAPI no dependan de la red), y se reutiliza.
_deps: Dependencias | None = None
_grafo_compilado = None


def configurar(deps: Dependencias) -> None:
    """Permite inyectar dependencias (simulador local, pruebas)."""
    global _deps, _grafo_compilado
    _deps, _grafo_compilado = deps, construir_grafo(deps)


def _grafo():
    if _grafo_compilado is None:
        configurar(crear_dependencias())
    return _grafo_compilado


def procesar_mensaje(remitente: str, texto: str = "", imagen: bytes | None = None,
                     id_citado: str | None = None, grafo=None) -> str | None:
    """
    Punto de entrada del webhook. Devuelve el texto a responder al remitente
    (o None si el agente ya envio lo necesario por su cuenta). `grafo`
    permite usar un grafo con otras dependencias (la demo web).
    """
    from app.limites import LimiteGeminiAlcanzado

    entrada = {"remitente": remitente, "mensaje": texto, "imagen": imagen,
               "id_citado": id_citado, "nlu": None, "respuesta": None}
    try:
        estado_final = (grafo or _grafo()).invoke(entrada)
        return estado_final.get("respuesta")
    except LimiteGeminiAlcanzado:
        # Tope diario de Gemini: se pausa el bot (los mensajes van a la propietaria) y se avisa.
        logger.error("Tope diario de Gemini alcanzado: bot en pausa")
        d = _deps
        if d is not None and not d.repo.bot_pausado():
            d.repo.pausar_bot(True)
            if d.propietaria:
                d.mensajero.enviar(d.propietaria, (
                    "⚠️ Se alcanzó el límite diario de uso del asistente. Lo pausé por seguridad: te reenvío "
                    "los mensajes de los clientes. Escribe \"activar bot\" cuando lo revisemos."))
            try:
                from app.notificaciones import correo
                if correo.configurado():
                    correo.enviar_correo("Lina's Pet Salón: límite diario de Gemini alcanzado",
                                         "El asistente se pausó al llegar al tope diario de llamadas a Gemini "
                                         "(MIA_LIMITE_GEMINI_DIA). Revisar si hay uso abusivo.")
            except Exception:  # noqa: BLE001
                logger.exception("No se pudo enviar el correo del limite de Gemini")
        try:
            return (grafo or _grafo()).invoke(entrada).get("respuesta")  # ahora va a la propietaria
        except Exception:  # noqa: BLE001
            return MENSAJE_ERROR
    except Exception:  # noqa: BLE001
        logger.exception("Error procesando mensaje de %s", remitente)
        return MENSAJE_ERROR


def get_reply(mensaje: str) -> str:
    """Compatibilidad con la firma de SCRUM-85 (texto entra, texto sale)."""
    return procesar_mensaje("local", mensaje) or ""
