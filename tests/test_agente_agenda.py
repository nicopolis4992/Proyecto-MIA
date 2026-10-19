"""
Pruebas del agente de agenda con el tarifario v2: orden de preguntas,
mestizos, cruces, deslanado que no aplica y rechazos. El LLM de extraccion
se reemplaza por respuestas JSON fijas.
"""

import json
from datetime import datetime

from conftest import ClienteFalso

from app.agenda.agente_agenda import AgenteAgenda
from app.agenda.disponibilidad import cargar_config
from app.config import ZONA_HORARIA
from app.cotizacion.cotizador import Cotizador
from app.mensajeria import MensajeroMemoria
from app.persistencia.repositorio import Repositorio

COT = Cotizador()
TEL, PROP = "593900000099", "593900000001"
AHORA = datetime(2026, 10, 5, 9, 0, tzinfo=ZONA_HORARIA)  # lunes


def _extraccion(mascotas, **reserva):
    base = {"fecha_hora": None, "modalidad": None, "sector": None, "cliente_nombre": None,
            "eligio_alternativa": None, "cancelar": False, "dia_consultado": None,
            "franja_preferida": None, "hora_minima": None, "pedido_especial": None,
            "pregunta_precio": False, "accion_cita": "ninguna"}
    campos = ("nombre", "servicio", "raza", "tamano", "peso_kg", "grupo", "estado", "comportamiento")
    return json.dumps({**base, **reserva,
                       "mascotas": [{c: m.get(c) for c in campos} for m in mascotas]})


def _agente(*respuestas, ya_preguntado=()):
    """`ya_preguntado`: preguntas que se dan por hechas (p. ej. la foto) para probar otra parte."""
    repo, msj = Repositorio(":memory:"), MensajeroMemoria()
    if ya_preguntado:
        # "foto": ya se pidio la foto las veces que corresponde (el cliente no la envio).
        repo.guardar_sesion(TEL, {"preguntado": [p for p in ya_preguntado if p != "foto"],
                                  **({"pedidos_foto": 2} if "foto" in ya_preguntado else {})})
    return AgenteAgenda(ClienteFalso(*respuestas), repo, msj, COT, cargar_config(), PROP), repo, msj


FOTO_Y_SALUD = ("tamano", "salud", "foto")


def test_mestizo_no_pregunta_el_tamaño_lo_da_la_foto():
    """18-oct: primero los datos del perro; el tamaño lo da la foto, que se pide al final."""
    m = {"nombre": "Toby", "servicio": "completo", "raza": "mestizo"}
    ag, _, _ = _agente(_extraccion([m]), _extraccion([m]), _extraccion([m]))
    respuestas = [ag.atender(TEL, t, AHORA) for t in ("quiero un baño completo para Toby, es mestizo",
                                                     "no tiene nudos", "le crece el pelo")]
    assert not any("pesa" in r or "miniatura" in r for r in respuestas)
    assert any("pelo" in r for r in respuestas)


def test_cruce_conocido_ya_no_pregunta_el_pelo():
    # schnauzer (A, tamano variable) x poodle (A, tamano variable): grupo resuelto.
    ag, _, _ = _agente(_extraccion([{"nombre": "Kira", "servicio": "completo",
                                     "raza": "schnauzer con poodle", "tamano": "pequeno"}]),
                       ya_preguntado=["tamano"])
    r = ag.atender(TEL, "es cruce de schnauzer con poodle, pequeñita", AHORA)
    assert "nudos" in r and "pelo" not in r.split("nudos")[0]


def test_nudos_y_comportamiento_se_preguntan_juntos_una_sola_vez():
    m = {"nombre": "Luna", "servicio": "completo", "raza": "golden"}
    ag, repo, _ = _agente(_extraccion([m]), _extraccion([m]), ya_preguntado=FOTO_Y_SALUD)
    r1 = ag.atender(TEL, "baño completo para mi golden Luna", AHORA)
    assert "nudos" in r1 and "nervioso" in r1 and "agresivo" in r1
    r2 = ag.atender(TEL, "no sé", AHORA)  # no responde: no se insiste
    assert "¿Qué día y a qué hora" in r2 and "puerta a puerta" not in r2   # 18-oct: no se ofrece


def test_deslanado_se_agenda_como_baño_completo():
    """Propietaria, 17-oct: el deslanado es parte del Baño Completo (doble capa y pelo corto)."""
    ag, repo, _ = _agente(_extraccion([{"nombre": "Max", "servicio": "deslanado", "raza": "husky"}]))
    ag.atender(TEL, "quiero deslanado para Max, es husky", AHORA)
    assert repo.obtener_sesion(TEL)["reserva"]["mascotas"][0]["servicio"] == "completo"


def test_perro_agresivo_se_rechaza_con_amabilidad():
    ag, repo, msj = _agente(_extraccion([{"nombre": "Rex", "servicio": "basico",
                                          "comportamiento": "agresivo_declarado"}]))
    r = ag.atender(TEL, "es un poco bravo, muerde", AHORA)
    assert "no lo atiende" in r or "agresivo" in r
    assert repo.citas_por_estado("pendiente_aprobacion") == []
    assert msj.enviados == []


def test_reserva_completa_crea_cita_y_avisa_a_la_propietaria():
    m = {"nombre": "Luna", "servicio": "completo", "raza": "golden", "estado": "sin_motas",
         "comportamiento": "tranquilo"}
    ag, repo, msj = _agente(_extraccion([m], modalidad="puerta_a_puerta", sector="Cotocollao",
                                        fecha_hora="2026-10-06T10:00"), ya_preguntado=FOTO_Y_SALUD)
    r = ag.atender(TEL, "golden Luna sin nudos tranquila, martes 10am, recojan en Cotocollao", AHORA)
    [cita] = repo.citas_por_estado("pendiente_aprobacion")
    assert cita["cotizacion"]["total"] == [30, 30]  # 25 + traslado zona 5
    assert "USD 30.00" in r
    assert "Total: 30$" in msj.a(PROP)[0]  # estilo de la propietaria (SCRUM-75)


# --- Despues de crear la cita (casos de la prueba manual del 06-oct) -------

def _cita_confirmada(repo, estado="confirmada"):
    m = {"nombre": "Fara", "servicio": "premium", "tamano": "mediano", "grupo": "B_deslanado",
         "estado": "sin_motas", "comportamiento": "tranquilo"}
    cot = COT.cotizar([m])
    cid = repo.crear_cita(cliente_telefono=TEL, mascotas=[m], fecha_hora=datetime(2026, 10, 12, 10, 0, tzinfo=ZONA_HORARIA),
                          modalidad="salon", cotizacion=cot, estado=estado, total_acordado=22)
    clave = {"confirmada": "cita_activa", "propuesta_cliente": "propuesta_cita"}[estado]
    repo.guardar_sesion(TEL, {clave: cid})
    return cid


def _extraccion_accion(accion, **extra):
    return json.dumps({"mascotas": [], "fecha_hora": None, "modalidad": None, "sector": None,
                       "cliente_nombre": None, "eligio_alternativa": None, "cancelar": False,
                       "dia_consultado": None, "franja_preferida": None, "hora_minima": None,
                       "pedido_especial": None, "pregunta_precio": False, "accion_cita": accion, **extra})


def test_cliente_acepta_la_propuesta_de_la_propietaria():
    ag, repo, msj = _agente()  # "si" se resuelve sin LLM
    cid = _cita_confirmada(repo, "propuesta_cliente")
    r = ag.atender(TEL, "sí", AHORA)
    assert "Queda agendado" in r
    assert repo.obtener_cita(cid)["estado"] == "confirmada"
    assert "aceptó el cambio" in msj.a(PROP)[0]


def test_a_esa_hora_no_puedo_reprograma_la_cita_existente():
    ag, repo, msj = _agente(_extraccion_accion("reprogramar"), _extraccion_accion("ninguna", eligio_alternativa=1))
    cid = _cita_confirmada(repo)
    r1 = ag.atender(TEL, "disculpa a esa hora no puedo", AHORA)
    assert "busquemos otro horario. Tengo libre" in r1 and "1." in r1                      # ofrece horarios, no "¿qué servicio?"
    assert repo.obtener_cita(cid)["estado"] == "en_reprogramacion"
    assert "pidió cambiar el horario" in msj.a(PROP)[0]
    r2 = ag.atender(TEL, "1", AHORA)
    cita = repo.obtener_cita(cid)
    assert cita["estado"] == "pendiente_aprobacion" and cita["ciclo_aprobacion"] == 2
    assert "el cliente eligió otro horario" in msj.a(PROP)[-1]
    assert len(repo.todas_las_citas()) == 1                          # misma cita, no una nueva
    assert cita["total_acordado"] == 22                               # el precio acordado se mantiene
    assert "Le confirmo" in r2


def test_otro_horario_ante_una_propuesta_reprograma_en_vez_de_aceptar():
    """Prueba con la propietaria (17-oct): propuesta para el lunes, la clienta pregunta por el
    martes y dice "martes a las 8 esta bien"; el bot confirmaba el LUNES."""
    ag, repo, msj = _agente(
        _extraccion_accion("aceptar_propuesta", fecha_hora="2026-10-13T08:00"))
    cid = _cita_confirmada(repo, "propuesta_cliente")
    r = ag.atender(TEL, "martes a las 8 esta bien", AHORA)
    cita = repo.obtener_cita(cid)
    assert "Queda agendado" not in r and cita["estado"] == "pendiente_aprobacion"
    assert cita["fecha_hora"].startswith("2026-10-13T08:00")
    assert "el cliente eligió otro horario" in msj.a(PROP)[-1]
    assert len(repo.todas_las_citas()) == 1 and cita["total_acordado"] == 22


def test_si_con_la_misma_hora_de_la_propuesta_si_acepta():
    ag, repo, _ = _agente(_extraccion_accion("aceptar_propuesta", fecha_hora="2026-10-12T10:00"))
    cid = _cita_confirmada(repo, "propuesta_cliente")
    assert "Queda agendado" in ag.atender(TEL, "si el lunes a las 10 perfecto", AHORA)
    assert repo.obtener_cita(cid)["estado"] == "confirmada"


def test_cuales_son_sus_horarios_responde_turnos_y_opciones_sin_repetir_la_pregunta():
    """Chat de prueba (16-oct): "Cuales son sus horarios?" -> "¿Que dia y a que hora...?" tres veces."""
    m = {"nombre": "Fara", "servicio": "completo", "tamano": "mediano", "grupo": "B_deslanado",
         "estado": "sin_motas", "comportamiento": "tranquilo"}
    ag, _, _ = _agente(_extraccion([m], modalidad="salon"), _extraccion([m], modalidad="salon"),
                       ya_preguntado=FOTO_Y_SALUD)
    assert ag.atender(TEL, "La llevo al salón", AHORA) == "¿Qué día y a qué hora le gustaría la cita?"
    r = ag.atender(TEL, "Cuales son sus horarios?", AHORA)
    assert ("lunes, miércoles y viernes a las 12:00, 14:00 y 16:00; martes, jueves, sábado y domingo "
            "a las 08:00, 10:00, 12:00, 14:00 y 16:00") in r
    assert "1." in r and "¿Qué día y a qué hora" not in r


def test_si_no_da_fecha_la_segunda_vez_ofrece_opciones():
    m = {"nombre": "Fara", "servicio": "completo", "tamano": "mediano", "grupo": "B_deslanado",
         "estado": "sin_motas", "comportamiento": "tranquilo"}
    ag, _, _ = _agente(_extraccion([m], modalidad="salon"), _extraccion([m], modalidad="salon"),
                       ya_preguntado=FOTO_Y_SALUD)
    ag.atender(TEL, "en el salón", AHORA)
    r = ag.atender(TEL, "cuando tenga espacio", AHORA)
    assert "horarios más cercanos" in r and "1." in r


def test_cliente_cancela_su_cita():
    ag, repo, msj = _agente(_extraccion_accion("cancelar_cita"))
    cid = _cita_confirmada(repo)
    assert "cancelé su cita" in ag.atender(TEL, "ya no voy a poder ir, cancélela", AHORA)
    assert repo.obtener_cita(cid)["estado"] == "cancelada"
    assert "canceló la cita" in msj.a(PROP)[0]


def test_gracias_tras_confirmar_no_abre_otra_reserva():
    ag, _, _ = _agente(_extraccion_accion("ninguna"))
    _cita_confirmada(ag.repo)
    r = ag.atender(TEL, "gracias!", AHORA)
    assert "sigue para el lunes 12 de octubre" in r and "servicio" not in r


def test_que_horarios_tiene_el_martes_ofrece_horarios_reales_sin_inventar_hora():
    m = {"nombre": "Toby", "servicio": "completo", "raza": "shih tzu", "estado": "sin_motas",
         "comportamiento": "tranquilo"}
    ag, repo, _ = _agente(_extraccion([m], modalidad="salon", dia_consultado="2026-10-06"),
                          ya_preguntado=FOTO_Y_SALUD)
    r = ag.atender(TEL, "¿qué horarios tiene el martes 6?", AHORA)
    assert "Para ese día tengo libre" in r and "martes 6 de octubre a las 08:00" in r   # abre a las 08:00
    assert repo.obtener_sesion(TEL)["reserva"]["fecha_hora"] is None


def test_opciones_repartidas_en_el_dia_y_respetan_la_tarde():
    """Antes ofrecia siempre 9, 10 y 11 (los tres primeros); y "en la tarde" se ignoraba.
    Con los turnos de 2 horas (17-oct) se reparten entre 08:00 y 16:00."""
    m = {"nombre": "Toby", "servicio": "completo", "raza": "shih tzu", "estado": "sin_motas",
         "comportamiento": "tranquilo"}
    ag, _, _ = _agente(_extraccion([m], modalidad="salon", dia_consultado="2026-10-08"),
                       ya_preguntado=FOTO_Y_SALUD)
    r = ag.atender(TEL, "¿qué horarios tiene el jueves 8?", AHORA)
    horas = [l.split(" a las ")[1] for l in r.splitlines() if " a las " in l]
    assert horas == ["08:00", "10:00", "12:00", "14:00", "16:00"], r   # 18-oct: todos los turnos libres

    # Lunes, miércoles y viernes abre a las 11: turnos de 12:00, 14:00 y 16:00 (propietaria, 18-oct).
    ag, _, _ = _agente(_extraccion([m], modalidad="salon", dia_consultado="2026-10-07"),
                       ya_preguntado=FOTO_Y_SALUD)
    r = ag.atender(TEL, "¿qué horarios tiene el miércoles 7?", AHORA)
    horas = [l.split(" a las ")[1] for l in r.splitlines() if " a las " in l]
    assert horas == ["12:00", "14:00", "16:00"], r

    ag, _, _ = _agente(_extraccion([m], modalidad="salon", dia_consultado="2026-10-07", franja_preferida="tarde"),
                       ya_preguntado=FOTO_Y_SALUD)
    r = ag.atender(TEL, "¿puede el miércoles en la tarde?", AHORA)
    horas = [l.split(" a las ")[1] for l in r.splitlines() if " a las " in l]
    assert horas and all(h >= "12:00" for h in horas), r


def test_reprogramar_pidiendo_la_tarde():
    ag, repo, _ = _agente(_extraccion_accion("reprogramar", franja_preferida="tarde"))
    _cita_confirmada(repo)
    r = ag.atender(TEL, "no a esa hora no puedo, ¿puede en la tarde?", AHORA)
    horas = [l.split(" a las ")[1] for l in r.splitlines() if " a las " in l]
    assert len(horas) >= 3 and all(h >= "12:00" for h in horas), r


def test_en_la_tarde_sin_dia_usa_el_dia_que_se_estaba_mirando():
    m = {"nombre": "Toby", "servicio": "completo", "raza": "shih tzu", "estado": "sin_motas",
         "comportamiento": "tranquilo"}
    ag, _, _ = _agente(_extraccion([m], modalidad="salon", dia_consultado="2026-10-07"),
                       _extraccion([m], modalidad="salon", franja_preferida="tarde"), ya_preguntado=FOTO_Y_SALUD)
    ag.atender(TEL, "¿qué horarios tiene el miércoles?", AHORA)
    r = ag.atender(TEL, "¿puede en la tarde?", AHORA)
    assert "miércoles 7 de octubre" in r and "lunes" not in r


# --- Pedidos especiales (06-oct): se anotan, sin precio salvo que lo pregunte ----

def test_premium_sin_baño_medicado_se_recomienda_el_completo_sin_cambiar_el_precio():
    """Propietaria, 18-oct: un Premium sin baño medicado es un Baño Completo; quitar algo no cambia el precio."""
    m = {"nombre": "Fara", "servicio": "premium", "tamano": "mediano", "grupo": "B_deslanado",
         "estado": "sin_motas", "comportamiento": "tranquilo"}
    ag, repo, msj = _agente(
        _extraccion([m], pedido_especial="sin baño medicado y sin accesorio"),
        _extraccion([m], modalidad="salon", fecha_hora="2026-10-07T12:00"),
        ya_preguntado=FOTO_Y_SALUD,
    )
    r1 = ag.atender(TEL, "¿puede hacerle el premium pero sin el baño medicado y sin el accesorio?", AHORA)
    assert "se lo agendo como Baño Completo" in r1
    r2 = ag.atender(TEL, "lo llevo yo, el miércoles a las 12", AHORA)
    [cita] = repo.citas_por_estado("pendiente_aprobacion")
    assert cita["mascotas"][0]["servicio"] == "completo"
    assert cita["cotizacion"]["total"] == COT.cotizar([{**m, "servicio": "completo"}])["total"]
    assert "USD" in r2 and "propietaria" not in r2
    assert "📝 Pedido del cliente: sin baño medicado y sin accesorio (no cambia el precio)" in msj.a(PROP)[0]


def test_quitar_algo_del_servicio_no_cambia_el_precio():
    m = {"nombre": "Fara", "servicio": "premium"}
    ag, _, _ = _agente(_extraccion([m], pedido_especial="sin accesorio", pregunta_precio=True))
    r = ag.atender(TEL, "sin accesorio, ¿cuánto me sale así?", AHORA)
    assert "El precio del servicio se mantiene" in r and "propietaria" not in r


def test_sin_reserva_en_curso_pasa_por_el_clasificador():
    from types import SimpleNamespace

    from app.agents.orchestrator_graph import enrutar_entrada

    repo = Repositorio(":memory:")
    d = SimpleNamespace(propietaria=PROP, repo=repo, agenda=SimpleNamespace(cita_vigente=lambda s, a: None))
    msg = {"remitente": TEL, "mensaje": "se llama Toby", "imagen": None}
    assert enrutar_entrada(msg, d) == "nlu"
    repo.guardar_sesion(TEL, {"flujo": "agendando"})
    assert enrutar_entrada(msg, d) == "agente_agenda"                       # sin llamada al NLU
    assert enrutar_entrada({**msg, "mensaje": "¿aceptan tarjeta?"}, d) == "nlu"


# -- SCRUM-75: resumen con origen, referido y estilo de la propietaria -------

def test_detectar_origen_y_referido():
    from app.agenda.origen import detectar
    assert detectar("Hola, me recomendó la Sra. Ana Pérez") == {"referido_por": "Ana Perez"}
    assert detectar("me lo recomendó mi vecina Rosa y quiero agendar") == {"referido_por": "Rosa"}
    assert detectar("lo dejé en el hospedaje la semana pasada") == {"origen": "hospedaje"}
    assert detectar("me pasó su número Lavet") == {"origen": "lavet"}
    assert detectar("¿tienen hospedaje?") == {}
    assert detectar("me recomendaron que lo bañe seguido") == {}


def test_resumen_al_estilo_de_la_propietaria():
    from app.agenda import mensajes
    cita = {"id": 3, "cliente_telefono": "593900000099", "cliente_nombre": "Rosa", "modalidad": "salon",
            "mascotas": [{"nombre": "Tita"}, {"nombre": "Cube"}, {"nombre": "Thomas"}],
            "cotizacion": {"mascotas": [{"rango": [25, 25]}, {"rango": [25, 25]}, {"rango": [12, 12]}],
                           "total": [62, 62], "descuento_multi_mascota": [0, 0]},
            "citas_previas": 2, "origen": "lavet", "referido_por": "Ana"}
    texto = mensajes.resumen_para_propietaria(cita)
    assert "25$ de Tita y Cube, y 12$ de Thomas. Total: 62$" in texto
    assert "cliente frecuente (2 cita(s) antes) · viene de Lavet · referido por Ana" in texto
    # Con rangos no hay linea de estilo: se muestra el total como rango.
    cita["cotizacion"]["mascotas"][2]["rango"] = [12, 15]
    cita["cotizacion"]["total"] = [62, 65]
    assert "Total: entre" in mensajes.resumen_para_propietaria(cita)


# --- Reunion con la propietaria (17-oct) -------------------------------------

def test_la_foto_se_pide_al_terminar_los_datos_y_hasta_dos_veces():
    m = {"nombre": "Toby", "servicio": "completo", "raza": "shih tzu", "estado": "sin_motas",
         "comportamiento": "tranquilo"}
    ag, _, _ = _agente(_extraccion([m]), _extraccion([m]), _extraccion([m]), ya_preguntado=["salud"])
    assert "foto actual de Toby" in ag.atender(TEL, "baño completo para Toby, es shih tzu", AHORA)
    assert "La foto de Toby nos ayuda" in ag.atender(TEL, "ahorita no tengo foto", AHORA)
    assert ag.atender(TEL, "no tengo", AHORA) == "¿Qué día y a qué hora le gustaría la cita?"


def test_vacunas_y_desparasitacion_se_anotan_para_la_propietaria():
    m = {"nombre": "Luna", "servicio": "completo", "raza": "golden", "estado": "sin_motas",
         "comportamiento": "tranquilo"}
    ag, repo, msj = _agente(_extraccion([m]), _extraccion([m], modalidad="salon", fecha_hora="2026-10-06T10:00"),
                            ya_preguntado=["foto"])
    assert ag.atender(TEL, "golden Luna, sin nudos y tranquila", AHORA) == "¿Tiene sus vacunas y la desparasitación al día?"
    ag.atender(TEL, "sí, vacunas al día; la desparasité hace 2 meses", AHORA)
    [cita] = repo.citas_por_estado("pendiente_aprobacion")
    assert "🩺 Vacunas y desparasitación: sí, vacunas al día; la desparasité hace 2 meses" in msj.a(PROP)[0]
    assert cita["mascotas"][0]["salud"].startswith("sí, vacunas al día")


def test_cliente_que_vuelve_no_repite_los_datos_de_su_mascota():
    """Memoria de clientes: Fara ya vino; se reconoce por el nombre y no se pide foto ni tamaño."""
    previa = {"nombre": "Fara", "servicio": "premium", "tamano": "mediano", "grupo": "B_deslanado",
              "estado": "sin_motas", "comportamiento": "tranquilo"}
    ag, repo, _ = _agente(_extraccion([{"nombre": "Fara", "servicio": "completo"}]))
    repo.crear_cita(cliente_telefono=TEL, mascotas=[previa], estado="confirmada", modalidad="salon",
                    fecha_hora=datetime(2026, 9, 20, 10, 0, tzinfo=ZONA_HORARIA), cotizacion=COT.cotizar([previa]))
    r = ag.atender(TEL, "quiero un baño completo para Fara", AHORA)
    fara = repo.obtener_sesion(TEL)["reserva"]["mascotas"][0]
    assert fara["tamano"] == "mediano" and fara["grupo"] == "B_deslanado"
    assert "foto" not in r and "nudos" in r


def test_cliente_que_vuelve_se_le_pregunta_si_es_para_la_misma_mascota():
    previa = {"nombre": "Fara", "servicio": "premium", "tamano": "mediano", "grupo": "B_deslanado"}
    ag, repo, _ = _agente(_extraccion([]))
    repo.crear_cita(cliente_telefono=TEL, mascotas=[previa], estado="confirmada", modalidad="salon",
                    fecha_hora=datetime(2026, 9, 20, 10, 0, tzinfo=ZONA_HORARIA), cotizacion=COT.cotizar([previa]))
    assert "¿Es para Fara?" in ag.atender(TEL, "hola, quiero agendar", AHORA)


def test_quiero_un_baño_para_mi_perrita_va_a_la_agenda_aunque_el_nlu_diga_consultar():
    from app.agents.orchestrator_graph import pide_servicio

    assert pide_servicio("Quiero un baño completo para mi perrita Fara, es mediana de doble capa")
    assert pide_servicio("quisiera agendar una cita para Toby")
    assert not pide_servicio("¿cuánto cuesta el baño completo?")
    assert not pide_servicio("quiero saber si aceptan tarjeta")


# --- Cambios del 18-oct -------------------------------------------------------

def test_pregunta_por_disponibilidad_antes_de_los_datos_dice_que_primero_hay_preguntas():
    m = {"nombre": "Toby", "servicio": "completo", "raza": "shih tzu"}
    ag, repo, _ = _agente(_extraccion([m], dia_consultado="2026-10-08"))
    r = ag.atender(TEL, "quiero un baño completo para Toby, ¿tiene el jueves?", AHORA)
    assert r.startswith("Con gusto le reviso la disponibilidad") and "Primero necesito" in r
    assert repo.obtener_sesion(TEL)["dia_consultado"] == "2026-10-08"


def test_al_llegar_a_la_fecha_muestra_el_dia_que_pregunto_antes():
    m = {"nombre": "Toby", "servicio": "completo", "raza": "shih tzu", "estado": "sin_motas",
         "comportamiento": "tranquilo"}
    ag, repo, _ = _agente(_extraccion([m]), ya_preguntado=FOTO_Y_SALUD)
    sesion = repo.obtener_sesion(TEL)
    repo.guardar_sesion(TEL, {**sesion, "dia_consultado": "2026-10-08"})
    r = ag.atender(TEL, "no tiene nudos", AHORA)
    assert "jueves 8 de octubre a las 08:00" in r and "jueves 8 de octubre a las 16:00" in r


def test_hay_cita_a_las_10_responde_y_espera_el_si():
    """18-oct: '¿hay cita a las 10?' se tomaba como confirmación de la cita."""
    m = {"nombre": "Toby", "servicio": "completo", "raza": "shih tzu", "estado": "sin_motas",
         "comportamiento": "tranquilo"}
    ag, repo, msj = _agente(_extraccion([m], fecha_hora="2026-10-08T10:00"), ya_preguntado=FOTO_Y_SALUD)
    r = ag.atender(TEL, "¿hay cita el jueves a las 10?", AHORA)
    assert "jueves 8 de octubre a las 10:00 está libre" in r and "¿Se lo reservo?" in r
    assert repo.citas_por_estado("pendiente_aprobacion") == [] and msj.a(PROP) == []
    r = ag.atender(TEL, "sí", AHORA)                                   # sin LLM
    [cita] = repo.citas_por_estado("pendiente_aprobacion")
    assert cita["fecha_hora"].startswith("2026-10-08T10:00") and "Tengo todo" in r


def test_hay_cita_a_una_hora_fuera_de_turno_ofrece_los_del_dia():
    m = {"nombre": "Toby", "servicio": "completo", "raza": "shih tzu", "estado": "sin_motas",
         "comportamiento": "tranquilo"}
    ag, repo, _ = _agente(_extraccion([m], fecha_hora="2026-10-08T11:00"), ya_preguntado=FOTO_Y_SALUD)
    r = ag.atender(TEL, "¿tiene a las 11 el jueves?", AHORA)
    assert "no está disponible" in r and "jueves 8 de octubre a las 10:00" in r
    assert repo.citas_por_estado("pendiente_aprobacion") == []


def test_la_foto_y_lo_que_vio_el_sistema_llegan_con_la_solicitud():
    """18-oct: la foto le llega a la propietaria junto con la solicitud y el precio propuesto."""
    import base64

    m = {"nombre": "Fara", "servicio": "completo", "tamano": "mediano", "grupo": "B_deslanado",
         "estado": "sin_motas", "comportamiento": "tranquilo"}
    ag, repo, msj = _agente(_extraccion([m], fecha_hora="2026-10-08T10:00"))
    traza = {"clasificacion": {"es_perro": True, "tamano": "mediano", "confianza_tamano": 0.92,
                               "grupo": "B_deslanado", "confianza_grupo": 0.81, "estado": "sin_motas",
                               "confianza_estado": 0.7, "backend": "cnn_onnx"}}
    repo.guardar_sesion(TEL, {"preguntado": ["salud"], "traza_foto": traza,
                              "fotos": [base64.b64encode(b"jpg").decode()]})
    ag.atender(TEL, "el jueves a las 10", AHORA)
    foto, resumen = msj.a(PROP)
    assert foto.startswith("📷 Foto de Fara (cita #1)")
    assert "📷 En la foto (CNN): mediano 92 %, doble capa 81 %, sin nudos 70 %" in resumen
    assert "USD" in resumen or "$" in resumen and "es grande" in resumen


def test_sin_puerta_a_puerta_salvo_que_lo_pida():
    m = {"nombre": "Fara", "servicio": "completo", "tamano": "mediano", "grupo": "B_deslanado",
         "estado": "sin_motas", "comportamiento": "tranquilo"}
    ag, repo, _ = _agente(_extraccion([m], fecha_hora="2026-10-08T10:00"), ya_preguntado=FOTO_Y_SALUD)
    ag.atender(TEL, "el jueves a las 10", AHORA)
    [cita] = repo.citas_por_estado("pendiente_aprobacion")
    assert cita["modalidad"] == "salon"
    ag, _, _ = _agente(_extraccion([m], modalidad="puerta_a_puerta"), ya_preguntado=FOTO_Y_SALUD)
    assert "sector" in ag.atender(TEL, "que la retiren en mi casa", AHORA)


def test_no_puedo_enviar_la_foto_no_cancela_la_reserva():
    """Grabacion del 18-oct: 'no puedo enviarla ahora' (la foto) se tomaba como cancelar."""
    m = {"nombre": "Fara", "servicio": "completo", "tamano": "mediano", "grupo": "B_deslanado",
         "estado": "sin_motas", "comportamiento": "tranquilo"}
    ag, repo, _ = _agente(_extraccion([m], cancelar=True), _extraccion([m], cancelar=True),
                          ya_preguntado=["salud"])
    ag.atender(TEL, "baño completo para Fara", AHORA)                 # pide la foto
    r = ag.atender(TEL, "no puedo enviarla ahora", AHORA)
    assert "no agendo nada" not in r and repo.obtener_sesion(TEL)["reserva"]["mascotas"]


def test_que_dias_tienen_disponibles_en_medio_de_los_datos():
    m = {"nombre": "Fara", "servicio": "completo"}
    ag, _, _ = _agente(_extraccion([m]), _extraccion([m]))
    ag.atender(TEL, "baño completo para Fara", AHORA)
    r = ag.atender(TEL, "que dias tienen disponibles?", AHORA)
    assert "Primero necesito hacerle unas preguntas sobre Fara" in r
    assert "nudos" in r      # repite la pregunta que no respondio, no la salta


def test_mas_informacion_responde_la_presentacion_sin_pasarlo_a_la_propietaria():
    """Prueba del 18-oct: 'encontre este lugar en instagram y quiero saber mas informacion'."""
    from app.agents.orchestrator_graph import (construir_grafo, crear_dependencias, pide_informacion_general,
                                               procesar_mensaje, pregunta_ubicacion)
    from app.agenda.origen import detectar

    texto = "buenas noches, encontre este lugar en instagram y quiero saber más informacion"
    assert pide_informacion_general(texto) and not pide_informacion_general("info del precio del baño")
    assert detectar(texto)["origen"] == "instagram"
    msj, repo = MensajeroMemoria(), Repositorio(":memory:")
    d = crear_dependencias(client=ClienteFalso(), repo=repo, mensajero=msj, propietaria=PROP,
                           agente_rag=lambda m: None, clasificador=object(), calendario=False)
    r = procesar_mensaje(TEL, texto, grafo=construir_grafo(d))
    assert "Somos Lina's Pet Salón" in r and "Baño Completo" in r and msj.a(PROP) == []
    assert repo.obtener_sesion(TEL)["cliente"]["origen"] == "instagram"
    assert pregunta_ubicacion("¿dónde quedan?") and pregunta_ubicacion("me pasa la ubicación")


def test_ubicacion_del_local_se_envia_como_pin(monkeypatch):
    from app.agents import orchestrator_graph as og

    cfg = {**cargar_config(), "ubicacion_local": {"nombre": "Lina's Pet Salón", "direccion": "El Condado",
                                                  "latitud": -0.1, "longitud": -78.5}}
    monkeypatch.setattr(og, "cargar_config", lambda: cfg)
    msj = MensajeroMemoria()
    d = og.crear_dependencias(client=ClienteFalso(), repo=Repositorio(":memory:"), mensajero=msj,
                              propietaria=PROP, agente_rag=lambda m: None, clasificador=object(), calendario=False)
    r = og.procesar_mensaje(TEL, "¿dónde quedan?", grafo=og.construir_grafo(d))
    assert "ubicación" in r and "El Condado" in msj.a(TEL)[0]
    assert "google.com/maps/search/?api=1&query=Lina%27s+Pet+Sal%C3%B3n%2C+El+Condado" in msj.a(TEL)[0]


def test_pregunta_con_la_cita_en_revision_la_responde_el_rag():
    """Prueba del 18-oct: con la cita enviada a aprobar, una pregunta recibia 'Estamos revisando su cita'."""
    from types import SimpleNamespace

    from app.agents.orchestrator_graph import construir_grafo, crear_dependencias, procesar_mensaje

    msj, repo = MensajeroMemoria(), Repositorio(":memory:")
    rag = lambda m: SimpleNamespace(texto="El pago es por transferencia al terminar.", fundamentada=True)
    d = crear_dependencias(client=ClienteFalso(_extraccion_accion("ninguna")), repo=repo, mensajero=msj,
                           propietaria=PROP, agente_rag=rag, clasificador=object(), calendario=False)
    m = {"nombre": "Fara", "servicio": "completo", "tamano": "mediano", "grupo": "B_deslanado"}
    cid = repo.crear_cita(cliente_telefono=TEL, mascotas=[m], modalidad="salon", cotizacion=COT.cotizar([m]),
                          fecha_hora=datetime(2099, 1, 5, 10, 0, tzinfo=ZONA_HORARIA))   # futura con el reloj real
    repo.guardar_sesion(TEL, {"cita_en_aprobacion": cid})
    r = procesar_mensaje(TEL, "¿el lunes cómo es el pago?", grafo=construir_grafo(d))   # va directo a la agenda
    assert r == "El pago es por transferencia al terminar."
