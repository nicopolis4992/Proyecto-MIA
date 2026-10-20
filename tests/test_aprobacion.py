"""
Pruebas de SCRUM-77 (procesar respuesta de la propietaria) y SCRUM-78
(confirmar / reprogramar con el cliente), mas la validacion de horarios.
"""

import json
from datetime import datetime

import pytest
from conftest import ClienteFalso

from app.agenda import mensajes
from app.agenda.aprobacion import ProcesadorAprobacion, interpretar_respuesta
from app.agenda.disponibilidad import cargar_config, proponer_alternativas, validar_horario
from app.config import RUTA_TARIFARIO, ZONA_HORARIA
from app.cotizacion.cotizador import Cotizador
from app.mensajeria import MensajeroMemoria
from app.persistencia.repositorio import Repositorio

MOTOR = Cotizador(RUTA_TARIFARIO)
CFG = cargar_config()
PROP, CLI = "593900000001", "593900000099"
# Jueves 1-oct-2026 (dia con restriccion vehicular declarada en el tarifario)
JUEVES_10 = datetime(2026, 10, 1, 10, 0, tzinfo=ZONA_HORARIA)


def _cita(repo, modalidad="puerta_a_puerta", fecha=JUEVES_10):
    luna = {"nombre": "Luna", "servicio": "completo", "raza": "golden", "estado": "sin_motas",
            "comportamiento": "tranquilo"}
    cot = MOTOR.cotizar([luna], modalidad, sector="El Condado")  # 25 + traslado 5
    cid = repo.crear_cita(cliente_telefono=CLI, mascotas=[luna],
                          fecha_hora=fecha, modalidad=modalidad, cotizacion=cot)
    repo.actualizar_cita(cid, msg_aprobacion_id=f"wamid.cita{cid}")
    repo.guardar_sesion(CLI, {"cita_en_aprobacion": cid})
    return cid


def _cliente_acepta(repo, msj, texto="sí"):
    """El cliente responde al precio que le llego tras la aprobacion (19-oct)."""
    from app.agenda.agente_agenda import AgenteAgenda

    agenda = AgenteAgenda(ClienteFalso(), repo, msj, MOTOR, CFG, PROP)
    return agenda.atender(CLI, texto, datetime(2026, 9, 30, 9, 0, tzinfo=ZONA_HORARIA))


def _procesador(cliente=None):
    repo, msj = Repositorio(":memory:"), MensajeroMemoria()
    return ProcesadorAprobacion(cliente or ClienteFalso(), repo, msj, MOTOR, CFG, PROP), repo, msj


@pytest.mark.parametrize("texto", ["listo", "Dale nomás", "OK", "sí", "👍"])
def test_aprobaciones_coloquiales_no_usan_llm(texto):
    cliente = ClienteFalso()
    assert interpretar_respuesta(texto, {"modalidad": "salon"}, cliente).tipo == "aprobar"
    assert cliente.llamadas == []


def test_aprobar_muestra_el_precio_y_confirma_cuando_el_cliente_acepta():
    """Propietaria, 19-oct: el precio se le dice al cliente al aprobar y la cita se confirma con su "sí"."""
    p, repo, msj = _procesador()
    cid = _cita(repo)
    resp = p.procesar("listo", id_citado=f"wamid.cita{cid}")
    assert "aprobada" in resp and "si acepta el precio" in resp
    assert repo.obtener_cita(cid)["estado"] == "propuesta_cliente"
    [precio] = msj.a(CLI)
    assert "jueves 1 de octubre a las 10:00" in precio and "30.00$" in precio and "¿Le confirmo la cita" in precio
    assert repo.obtener_sesion(CLI)["propuesta_cita"] == cid
    confirmacion = _cliente_acepta(repo, msj)
    assert "Queda agendado" in confirmacion and "pendiente en casa" in confirmacion   # puerta a puerta
    assert repo.obtener_cita(cid)["estado"] == "confirmada"
    assert "El cliente aceptó" in msj.a(PROP)[-1]
    tipos = [e["tipo"] for e in repo.eventos_de_cita(cid)]
    assert tipos[:4] == ["creada", "respuesta_propietaria", "aprobada", "precio_enviado_al_cliente"]
    assert "confirmada" in tipos


def test_si_el_cliente_no_acepta_el_precio_vuelve_a_la_propietaria():
    import json as _json

    p, repo, msj = _procesador()
    cid = _cita(repo)
    p.procesar("listo", id_citado=f"wamid.cita{cid}")
    from app.agenda.agente_agenda import AgenteAgenda

    rechazo = _json.dumps({"mascotas": [], "fecha_hora": None, "modalidad": None, "sector": None,
                           "cliente_nombre": None, "eligio_alternativa": None, "cancelar": False,
                           "dia_consultado": None, "franja_preferida": None, "hora_minima": None,
                           "pedido_especial": None, "pregunta_precio": False, "accion_cita": "rechazar_propuesta"})
    agenda = AgenteAgenda(ClienteFalso(rechazo), repo, msj, MOTOR, CFG, PROP)
    r = agenda.atender(CLI, "uy está muy caro", datetime(2026, 9, 30, 9, 0, tzinfo=ZONA_HORARIA))
    assert r == "Entiendo 🙏 Lo reviso y le escribo en un momento."
    assert repo.obtener_cita(cid)["estado"] == "pendiente_aprobacion"
    assert "no aceptó el precio" in msj.a(PROP)[-1]


def test_rechazar_ofrece_alternativas_validas_y_reabre_la_reserva():
    p, repo, msj = _procesador()
    cid = _cita(repo)
    p.procesar("no", ahora=datetime(2026, 9, 30, 9, 0, tzinfo=ZONA_HORARIA))
    assert repo.obtener_cita(cid)["estado"] == "rechazada"
    [oferta] = msj.a(CLI)
    assert "1." in oferta and "2." in oferta
    sesion = repo.obtener_sesion(CLI)
    assert sesion["flujo"] == "agendando" and sesion["reserva"]["fecha_hora"] is None
    for alt in sesion["alternativas"]:
        ok, _ = validar_horario(datetime.fromisoformat(alt), 60, "puerta_a_puerta", MOTOR, CFG)
        assert ok


def test_modificar_hora_se_propone_al_cliente_sin_confirmar():
    """La propietaria cambia la hora: el CLIENTE decide, no se confirma solo."""
    llm = json.dumps({"tipo": "modificar", "nueva_fecha_hora": "2026-10-01T12:00",
                      "nuevo_total": 22, "nuevo_costo_transporte": None, "motivo": None})
    p, repo, msj = _procesador(ClienteFalso(llm))
    cid = _cita(repo)
    resp = p.procesar("cámbialo a las 12 y cóbrale 22", id_citado=f"wamid.cita{cid}")
    assert "Le propuse el cambio" in resp and "22.00$" in resp
    cita = repo.obtener_cita(cid)
    assert cita["estado"] == "propuesta_cliente" and cita["ciclo_aprobacion"] == 2
    assert cita["fecha_hora"].startswith("2026-10-01T12:00")
    [propuesta] = msj.a(CLI)
    assert "¿Le parece bien?" in propuesta and "12:00" in propuesta
    assert "Queda agendado" not in propuesta
    assert repo.obtener_sesion(CLI)["propuesta_cita"] == cid


def test_el_lunes_no_puedo_con_otro_precio_pide_otro_dia_al_cliente():
    """Prueba con la propietaria (17-oct): "el lunes no puedo, el total del cobro seria $22"
    le volvia a proponer el MISMO lunes. Ahora la cita se reabre y se ofrecen otros dias."""
    llm = json.dumps({"tipo": "modificar", "nueva_fecha_hora": None, "nuevo_total": 22,
                      "nuevo_costo_transporte": None, "motivo": "no puede el lunes"})
    p, repo, msj = _procesador(ClienteFalso(llm))
    cid = _cita(repo, modalidad="salon", fecha=datetime(2026, 10, 19, 12, 0, tzinfo=ZONA_HORARIA))
    resp = p.procesar("el lunes no puedo, el total del cobro seria $22", id_citado=f"wamid.cita{cid}",
                      ahora=datetime(2026, 10, 16, 20, 0, tzinfo=ZONA_HORARIA))
    assert "Le pedí al cliente otro horario" in resp and "22.00$" in resp
    cita = repo.obtener_cita(cid)
    assert cita["estado"] == "en_reprogramacion" and cita["total_acordado"] == 22
    [aviso] = msj.a(CLI)
    assert "lunes 19 de octubre ya no tenemos espacio" in aviso and "22.00$" in aviso
    assert "propietaria" not in aviso
    opciones = [l for l in aviso.splitlines() if l.split(".")[0].isdigit()]
    assert opciones and not any("lunes 19" in o for o in opciones)
    sesion = repo.obtener_sesion(CLI)
    assert sesion["reprogramar_cita_id"] == cid and len(sesion["alternativas"]) == len(opciones)


def test_respuesta_de_la_propietaria_a_una_consulta_se_reenvia_al_cliente():
    p, repo, msj = _procesador()
    p.registrar_consulta("wamid.consulta1", CLI, "¿qué horarios tiene el martes?")
    resp = p.procesar("desde las 10:30 en adelante", id_citado="wamid.consulta1")
    assert "Se lo envié" in resp
    assert msj.a(CLI) == ["desde las 10:30 en adelante"]   # 18-oct: tal cual, en nombre del salón


def test_modificar_transporte_recalcula_total():
    llm = json.dumps({"tipo": "modificar", "nueva_fecha_hora": None, "nuevo_total": None,
                      "nuevo_costo_transporte": 2, "motivo": None})
    p, repo, _ = _procesador(ClienteFalso(llm))
    cid = _cita(repo)
    assert repo.obtener_cita(cid)["cotizacion"]["total"] == [30, 30]
    p.procesar("en 2$ le dejo el transporte")
    cita = repo.obtener_cita(cid)
    assert cita["cotizacion"]["total"] == [27, 27]
    assert "Total: 27$" in mensajes.resumen_para_propietaria(cita)


def test_varias_pendientes_sin_cita_referenciada_pide_aclarar():
    p, repo, _ = _procesador()
    a, b = _cita(repo), _cita(repo)
    resp = p.procesar("listo")
    assert f"#{a}" in resp and f"#{b}" in resp
    assert repo.obtener_cita(a)["estado"] == "pendiente_aprobacion"


def test_pico_y_placa_bloquea_puerta_a_puerta_pero_no_salon():
    jueves_16 = JUEVES_10.replace(hour=16)
    ok, motivo = validar_horario(jueves_16, 60, "puerta_a_puerta", MOTOR, CFG)
    assert not ok and "restricción" in motivo
    assert validar_horario(jueves_16, 60, "salon", MOTOR, CFG)[0]
    alternativas = proponer_alternativas(jueves_16, 60, "puerta_a_puerta", MOTOR, CFG)
    assert alternativas and all(a.hour < 16 or a.date() != jueves_16.date() for a in alternativas)


def test_solo_se_agenda_en_turnos_de_dos_horas():
    """Propietaria, 17-oct: 'agenda a 2 horas desde las 8 hasta las 4'."""
    ok, motivo = validar_horario(JUEVES_10.replace(hour=11), 60, "salon", MOTOR, CFG)
    assert not ok and "08:00, 10:00, 12:00, 14:00 y 16:00" in motivo           # jueves abre a las 8
    lunes_10 = datetime(2026, 10, 5, 10, 0, tzinfo=ZONA_HORARIA)
    ok, motivo = validar_horario(lunes_10, 60, "salon", MOTOR, CFG)
    assert not ok and "11:00, 13:00 y 15:00" in motivo
    alternativas = proponer_alternativas(JUEVES_10.replace(hour=11), 60, "salon", MOTOR, CFG)
    assert alternativas and all(a.hour in ((11, 13, 15) if a.weekday() in (0, 2, 4) else (8, 10, 12, 14, 16))
                                and a.minute == 0 for a in alternativas)


def test_confirmacion_incluye_total_y_traslado():
    p, repo, msj = _procesador()
    cid = _cita(repo)
    p.procesar("listo", id_citado=f"wamid.cita{cid}")
    [precio] = msj.a(CLI)
    assert "Baño Completo" in precio and "30.00$ (con el servicio puerta a puerta)" in precio
    assert "30.00$ con el servicio puerta a puerta incluido" in _cliente_acepta(repo, msj)


# -- cobro real (SCRUM-95) ---------------------------------------------------

DESPUES = datetime(2026, 10, 1, 18, 0, tzinfo=ZONA_HORARIA)


@pytest.mark.parametrize("texto,esperado", [
    ("cobré 22 a la cita #5", (22.0, 5)), ("#5 cobré 22", (22.0, 5)),
    ("le cobramos 18,50", (18.5, None)), ("cobrado $30 cita 7", (30.0, 7)),
    ("cóbrale 20", None), ("listo", None),
])
def test_leer_cobro(texto, esperado):
    from app.agenda.aprobacion import leer_cobro
    assert leer_cobro(texto) == esperado


def test_cobro_se_registra_sin_llm_y_alimenta_la_desviacion():
    from app.panel.datos import desviacion_cobro, resumen
    cliente = ClienteFalso()
    p, repo, msj = _procesador(cliente)
    cid = _cita(repo)
    p.procesar("listo", id_citado=f"wamid.cita{cid}")
    _cliente_acepta(repo, msj)
    resp = p.procesar("cobré 33", ahora=DESPUES)  # una sola cita atendida: no hace falta el numero
    assert "registré 33.00$" in resp
    cita = repo.obtener_cita(cid)
    assert cita["total_cobrado"] == 33.0
    assert repo.eventos_de_cita(cid)[-1]["tipo"] == "cobrada"
    assert cliente.llamadas == []
    assert desviacion_cobro(cita) == pytest.approx(3.0)  # cotizado 30 (25 + traslado 5)
    k = resumen(repo)["kpis"]
    assert k["citas_cobradas"] == 1 and k["desviacion_media_usd"] == 3.0


def test_cobro_dentro_del_rango_no_es_desviacion():
    from app.panel.datos import desviacion_cobro
    base = {"cotizacion": {"total": [20, 25]}}
    assert desviacion_cobro({**base, "total_cobrado": 22}) == 0
    assert desviacion_cobro({**base, "total_cobrado": 27}) == 2
    assert desviacion_cobro({**base, "total_cobrado": 22, "total_acordado": 20}) == 2


def test_cobro_ambiguo_pide_el_numero_y_no_registra_en_citas_sin_confirmar():
    p, repo, _ = _procesador()
    a, b = _cita(repo), _cita(repo)
    for cid in (a, b):
        repo.actualizar_cita(cid, estado="confirmada")
    assert "¿A qué cita" in p.procesar("cobré 25", ahora=DESPUES)
    assert "Sin cobro registrado" in p.procesar("por cobrar", ahora=DESPUES)
    assert "registré 25.00$" in p.procesar(f"cobré 25 a la cita #{b}", ahora=DESPUES)
    assert f"#{a}" in p.procesar("por cobrar", ahora=DESPUES)
    c = _cita(repo)  # pendiente de aprobacion
    assert "no está confirmada" in p.procesar(f"cobré 25 cita #{c}", ahora=DESPUES)
    assert repo.obtener_cita(c)["total_cobrado"] is None


def test_aprobar_con_numero_de_cita_sin_citar_el_mensaje():
    """Desde el correo de respaldo no se puede citar: "listo #N" basta (sin LLM)."""
    cliente = ClienteFalso()
    p, repo, _ = _procesador(cliente)
    a, b = _cita(repo), _cita(repo)
    assert "aprobada" in p.procesar(f"listo #{b}")
    assert repo.obtener_cita(b)["estado"] == "propuesta_cliente"
    assert repo.obtener_cita(a)["estado"] == "pendiente_aprobacion"
    assert cliente.llamadas == []
    assert "ya está aprobada" in p.procesar(f"listo #{b}")      # no se le reenvía el precio al cliente


# -- plan de contingencia: pausar el bot (SCRUM-92) ----------------------------

def test_pausar_bot_reenvia_a_la_propietaria_y_su_respuesta_vuelve_al_cliente():
    from types import SimpleNamespace

    from app.agents.orchestrator_graph import enrutar_entrada, nodo_pausado

    cliente = ClienteFalso()
    p, repo, msj = _procesador(cliente)
    d = SimpleNamespace(propietaria=PROP, repo=repo, mensajero=msj, aprobacion=p,
                        agenda=SimpleNamespace(cita_vigente=lambda s, a: None))
    msg = {"remitente": CLI, "mensaje": "hola, quiero agendar", "imagen": None, "id_citado": None}

    assert "Bot en pausa" in p.procesar("Pausar bot")
    assert repo.bot_pausado()
    assert enrutar_entrada(msg, d) == "pausado"
    assert nodo_pausado(dict(msg), d)["respuesta"] is None         # el bot no le contesta
    [aviso] = msj.a(PROP)
    assert "hola, quiero agendar" in aviso and CLI in aviso
    id_aviso = msj.enviados[-1][2]
    p.procesar("Hola! Sí claro, ¿para cuándo?", id_citado=id_aviso)  # responde citando
    assert msj.a(CLI) == ["Hola! Sí claro, ¿para cuándo?"]
    assert cliente.llamadas == []                                    # sin Gemini

    assert "activo" in p.procesar("activar bot")
    assert not repo.bot_pausado()
    assert enrutar_entrada(msg, d) != "pausado"


def test_indicadores_de_supervision_humana_en_el_panel():
    """Riesgo de sello automatico: % aprobadas sin cambios y tiempo de decision."""
    import json as _json
    from app.panel.datos import indicadores_aprobacion

    llm = _json.dumps({"tipo": "modificar", "nueva_fecha_hora": "2026-10-01T12:00", "nuevo_total": None,
                       "nuevo_costo_transporte": None, "motivo": None})
    p, repo, _ = _procesador(ClienteFalso(llm))
    a, b = _cita(repo), _cita(repo)
    for cid in (a, b):
        repo.registrar_evento(cid, "enviada_a_propietaria")
    p.procesar("listo", id_citado=f"wamid.cita{a}")
    p.procesar("a las 12 mejor", id_citado=f"wamid.cita{b}")
    k = indicadores_aprobacion(repo, repo.todas_las_citas())
    assert k["decisiones_propietaria"] == 2
    assert k["pct_aprobadas_sin_cambios"] == 50 and k["pct_modificadas"] == 50
    assert k["tiempo_decision_mediana_min"] is not None


def test_es_grande_tras_ver_la_foto_recotiza_y_luego_listo_aprueba():
    p, repo, msj = _procesador()
    cid = _cita(repo, modalidad="salon")
    antes = repo.obtener_cita(cid)["cotizacion"]["total"]
    resp = p.procesar("es grande", id_citado=f"wamid.cita{cid}")              # sin LLM
    cita = repo.obtener_cita(cid)
    assert "tamaño corregido" in resp and cita["mascotas"][0]["tamano"] == "grande"
    assert cita["estado"] == "pendiente_aprobacion" and msj.a(CLI) == []
    assert cita["cotizacion"]["total"] == MOTOR.cotizar([{**cita["mascotas"][0]}], "salon")["total"]
    p.procesar("listo", id_citado=f"wamid.cita{cid}")
    assert repo.obtener_cita(cid)["estado"] == "propuesta_cliente" and antes is not None


def test_es_mediana_listo_corrige_y_aprueba_en_un_mensaje():
    p, repo, msj = _procesador()
    cid = _cita(repo, modalidad="salon")
    p.procesar("es mediana, listo", id_citado=f"wamid.cita{cid}")
    cita = repo.obtener_cita(cid)
    assert cita["estado"] == "propuesta_cliente" and cita["mascotas"][0]["tamano"] == "mediano"


def test_error_del_calendario_se_explica():
    from types import SimpleNamespace

    from app.agenda.calendario import explicar_error

    def error(codigo, mensaje):
        r = SimpleNamespace(status_code=codigo, json=lambda: {"error": {"message": mensaje}})
        return SimpleNamespace(response=r)

    assert "compartido" in explicar_error(error(404, "Not Found"))
    assert "no está habilitada" in explicar_error(error(403, "Google Calendar API has not been used in project"))
    assert "Hacer cambios en los eventos" in explicar_error(error(403, "Forbidden"))


def test_cambio_de_hora_y_precio_citando_una_consulta_se_aplica_a_la_cita():
    """Prueba del 18-oct: la ultima notificacion era una consulta del cliente; la propietaria
    escribio el cambio de la cita y se le reenvio tal cual al cliente."""
    llm = json.dumps({"tipo": "modificar", "nueva_fecha_hora": "2026-10-01T14:00", "nuevo_total": 20,
                      "nuevo_costo_transporte": None, "motivo": None})
    p, repo, msj = _procesador(ClienteFalso(llm))
    cid = _cita(repo, modalidad="salon")
    p.registrar_consulta("wamid.consulta9", CLI, "me puedes dar la direccion?")
    resp = p.procesar("el jueves a las 12 no puedo, cambialo para las 2pm. el precio cambialo a 20",
                      id_citado="wamid.consulta9")
    cita = repo.obtener_cita(cid)
    assert "Le propuse el cambio" in resp and cita["total_acordado"] == 20
    assert cita["fecha_hora"].startswith("2026-10-01T14:00")
    assert not any("cambialo" in t for t in msj.a(CLI))       # no se reenvia el texto de la propietaria


def test_respuesta_a_una_consulta_sin_cita_pendiente_se_reenvia():
    p, repo, msj = _procesador()
    p.registrar_consulta("wamid.c2", CLI, "¿aceptan tarjeta?")
    p.procesar("sí, aceptamos tarjeta", id_citado="wamid.c2")
    assert msj.a(CLI) == ["sí, aceptamos tarjeta"]


def test_indicador_tamano_por_foto_frente_a_la_propietaria():
    """Base para aprender de sus correcciones: Gemini dijo pequeño, ella dijo grande."""
    from app.panel.datos import indicador_foto

    p, repo, _ = _procesador()
    a, b = _cita(repo, modalidad="salon"), _cita(repo, modalidad="salon")
    for cid, tam in ((a, "pequeno"), (b, "mediano")):
        repo.registrar_evento(cid, "cotizacion_por_foto", {"clasificacion": {"tamano": tam}})
    p.procesar("es grande", id_citado=f"wamid.cita{a}")          # corrige: era grande
    p.procesar("listo", id_citado=f"wamid.cita{a}")
    p.procesar("listo", id_citado=f"wamid.cita{b}")              # aprueba sin corregir: acierto
    r = indicador_foto(repo, repo.todas_las_citas())
    assert r["fotos_evaluadas"] == 2 and r["pct_tamano_acertado"] == 50
    assert r["fotos_subestimadas"] == 1 and r["fotos_sobreestimadas"] == 0
