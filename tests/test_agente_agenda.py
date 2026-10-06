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


def _agente(*respuestas):
    repo, msj = Repositorio(":memory:"), MensajeroMemoria()
    return AgenteAgenda(ClienteFalso(*respuestas), repo, msj, COT, cargar_config(), PROP), repo, msj


def test_mestizo_pregunta_primero_el_tamano_y_luego_el_pelo():
    ag, _, _ = _agente(
        _extraccion([{"nombre": "Toby", "servicio": "completo", "raza": "mestizo"}]),
        _extraccion([{"nombre": "Toby", "servicio": "completo", "raza": "mestizo", "tamano": "mediano"}]),
    )
    r1 = ag.atender(TEL, "quiero un baño completo para Toby, es mestizo", AHORA)
    assert "pesa" in r1 and "foto" in r1
    r2 = ag.atender(TEL, "es mediano", AHORA)
    assert "pelo" in r2


def test_cruce_conocido_ya_no_pregunta_el_pelo():
    # schnauzer (A, tamano variable) x poodle (A, tamano variable): grupo resuelto.
    ag, _, _ = _agente(_extraccion([{"nombre": "Kira", "servicio": "completo",
                                     "raza": "schnauzer con poodle", "tamano": "pequeno"}]))
    r = ag.atender(TEL, "es cruce de schnauzer con poodle, pequeñita", AHORA)
    assert "nudos" in r and "pelo" not in r.split("nudos")[0]


def test_nudos_y_comportamiento_se_preguntan_juntos_una_sola_vez():
    m = {"nombre": "Luna", "servicio": "completo", "raza": "golden"}
    ag, repo, _ = _agente(_extraccion([m]), _extraccion([m]))
    r1 = ag.atender(TEL, "baño completo para mi golden Luna", AHORA)
    assert "nudos" in r1 and "nervioso" in r1
    r2 = ag.atender(TEL, "no sé", AHORA)  # no responde: no se insiste
    assert "salón" in r2


def test_deslanado_a_shih_tzu_sugiere_completo_y_vuelve_a_preguntar_servicio():
    ag, repo, _ = _agente(_extraccion([{"nombre": "Max", "servicio": "deslanado", "raza": "shitsu"}]))
    r = ag.atender(TEL, "quiero deslanado para Max, es shitsu", AHORA)
    assert "doble capa" in r and "Baño Completo" in r
    assert repo.obtener_sesion(TEL)["reserva"]["mascotas"][0]["servicio"] is None


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
                                        fecha_hora="2026-10-06T10:00"))
    r = ag.atender(TEL, "golden Luna sin nudos tranquila, martes 10am, recojan en Cotocollao", AHORA)
    [cita] = repo.citas_por_estado("pendiente_aprobacion")
    assert cita["cotizacion"]["total"] == [30, 30]  # 25 + traslado zona 5
    assert "USD 30.00" in r
    assert "30.00$" in msj.a(PROP)[0]


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
    assert "busquemos otro horario. Le puedo ofrecer" in r1 and "1." in r1                      # ofrece horarios, no "¿qué servicio?"
    assert repo.obtener_cita(cid)["estado"] == "en_reprogramacion"
    assert "pidió cambiar el horario" in msj.a(PROP)[0]
    r2 = ag.atender(TEL, "1", AHORA)
    cita = repo.obtener_cita(cid)
    assert cita["estado"] == "pendiente_aprobacion" and cita["ciclo_aprobacion"] == 2
    assert "reprogramada por el cliente" in msj.a(PROP)[-1]
    assert len(repo.todas_las_citas()) == 1                          # misma cita, no una nueva
    assert cita["total_acordado"] == 22                               # el precio acordado se mantiene
    assert "Le confirmo" in r2


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
    ag, repo, _ = _agente(_extraccion([m], modalidad="salon", dia_consultado="2026-10-06"))
    r = ag.atender(TEL, "¿qué horarios tiene el martes 6?", AHORA)
    assert "Para ese día tengo libre" in r and "martes 6 de octubre a las 09:00" in r
    assert repo.obtener_sesion(TEL)["reserva"]["fecha_hora"] is None


def test_opciones_repartidas_en_el_dia_y_respetan_la_tarde():
    """Antes ofrecia siempre 9, 10 y 11 (los tres primeros); y "en la tarde" se ignoraba."""
    m = {"nombre": "Toby", "servicio": "completo", "raza": "shih tzu", "estado": "sin_motas",
         "comportamiento": "tranquilo"}
    ag, _, _ = _agente(_extraccion([m], modalidad="salon", dia_consultado="2026-10-07"))
    r = ag.atender(TEL, "¿qué horarios tiene el miércoles 7?", AHORA)
    assert "09:00" in r and "11:00" not in r.split("3.")[0] and "16:00" in r   # mañana ... tarde

    ag, _, _ = _agente(_extraccion([m], modalidad="salon", dia_consultado="2026-10-07", franja_preferida="tarde"))
    r = ag.atender(TEL, "¿puede el miércoles en la tarde?", AHORA)
    horas = [l.split(" a las ")[1] for l in r.splitlines() if " a las " in l]
    assert horas and all(h >= "12:00" for h in horas), r


def test_reprogramar_pidiendo_la_tarde():
    ag, repo, _ = _agente(_extraccion_accion("reprogramar", franja_preferida="tarde"))
    _cita_confirmada(repo)
    r = ag.atender(TEL, "no a esa hora no puedo, ¿puede en la tarde?", AHORA)
    horas = [l.split(" a las ")[1] for l in r.splitlines() if " a las " in l]
    assert len(horas) == 3 and all(h >= "12:00" for h in horas), r


def test_en_la_tarde_sin_dia_usa_el_dia_que_se_estaba_mirando():
    m = {"nombre": "Toby", "servicio": "completo", "raza": "shih tzu", "estado": "sin_motas",
         "comportamiento": "tranquilo"}
    ag, _, _ = _agente(_extraccion([m], modalidad="salon", dia_consultado="2026-10-07"),
                       _extraccion([m], modalidad="salon", franja_preferida="tarde"))
    ag.atender(TEL, "¿qué horarios tiene el miércoles?", AHORA)
    r = ag.atender(TEL, "¿puede en la tarde?", AHORA)
    assert "miércoles 7 de octubre" in r and "lunes" not in r


# --- Pedidos especiales (06-oct): se anotan, sin precio salvo que lo pregunte ----

def test_pedido_especial_se_anota_sin_mencionar_precio():
    m = {"nombre": "Fara", "servicio": "premium", "tamano": "mediano", "grupo": "B_deslanado",
         "estado": "sin_motas", "comportamiento": "tranquilo"}
    ag, repo, msj = _agente(
        _extraccion([m], pedido_especial="sin baño medicado y sin accesorio"),
        _extraccion([m], modalidad="salon", fecha_hora="2026-10-07T10:00"),
    )
    r1 = ag.atender(TEL, "¿puede hacerle el premium pero sin el baño medicado y sin el accesorio?", AHORA)
    assert "Anoto su pedido: sin baño medicado y sin accesorio" in r1
    assert "$" not in r1 and "USD" not in r1
    r2 = ag.atender(TEL, "lo llevo yo, el miércoles a las 10", AHORA)
    assert "USD" not in r2 and "lo confirma la propietaria" in r2
    [cita] = repo.citas_por_estado("pendiente_aprobacion")
    assert cita["pedido_especial"] == "sin baño medicado y sin accesorio"
    assert "⚠️ Pedido especial del cliente: sin baño medicado y sin accesorio" in msj.a(PROP)[0]


def test_si_pregunta_el_precio_del_pedido_se_dice_que_lo_valida_la_propietaria():
    m = {"nombre": "Fara", "servicio": "premium"}
    ag, _, _ = _agente(_extraccion([m], pedido_especial="sin accesorio", pregunta_precio=True))
    r = ag.atender(TEL, "sin accesorio, ¿cuánto me sale así?", AHORA)
    assert "le confirma el precio con ese cambio" in r and "USD" not in r


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
