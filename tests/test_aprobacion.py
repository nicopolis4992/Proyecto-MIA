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


def _procesador(cliente=None):
    repo, msj = Repositorio(":memory:"), MensajeroMemoria()
    return ProcesadorAprobacion(cliente or ClienteFalso(), repo, msj, MOTOR, CFG, PROP), repo, msj


@pytest.mark.parametrize("texto", ["listo", "Dale nomás", "OK", "sí", "👍"])
def test_aprobaciones_coloquiales_no_usan_llm(texto):
    cliente = ClienteFalso()
    assert interpretar_respuesta(texto, {"modalidad": "salon"}, cliente).tipo == "aprobar"
    assert cliente.llamadas == []


def test_aprobar_confirma_y_notifica_al_cliente():
    p, repo, msj = _procesador()
    cid = _cita(repo)
    resp = p.procesar("listo", id_citado=f"wamid.cita{cid}")
    assert "confirmada" in resp
    assert repo.obtener_cita(cid)["estado"] == "confirmada"
    [confirmacion] = msj.a(CLI)
    assert "jueves 1 de octubre a las 10:00" in confirmacion
    assert "pendiente en casa" in confirmacion  # puerta a puerta
    tipos = [e["tipo"] for e in repo.eventos_de_cita(cid)]
    assert tipos == ["creada", "respuesta_propietaria", "aprobada", "confirmada"]
    assert repo.obtener_sesion(CLI)["cita_en_aprobacion"] is None


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


def test_modificar_hora_abre_nuevo_ciclo_con_la_propietaria():
    llm = json.dumps({"tipo": "modificar", "nueva_fecha_hora": "2026-10-01T12:00",
                      "nuevo_total": None, "nuevo_costo_transporte": None, "motivo": None})
    p, repo, msj = _procesador(ClienteFalso(llm))
    cid = _cita(repo)
    assert p.procesar("a las 12 estaría bien", id_citado=f"wamid.cita{cid}") is None
    cita = repo.obtener_cita(cid)
    assert cita["estado"] == "pendiente_aprobacion" and cita["ciclo_aprobacion"] == 2
    assert cita["fecha_hora"].startswith("2026-10-01T12:00")
    assert msj.a(CLI) == []                       # al cliente aun no se le dice nada
    assert "revisión 2" in msj.a(PROP)[-1]
    assert cita["msg_aprobacion_id"] == msj.enviados[-1][2]


def test_modificar_transporte_recalcula_total():
    llm = json.dumps({"tipo": "modificar", "nueva_fecha_hora": None, "nuevo_total": None,
                      "nuevo_costo_transporte": 2, "motivo": None})
    p, repo, _ = _procesador(ClienteFalso(llm))
    cid = _cita(repo)
    assert repo.obtener_cita(cid)["cotizacion"]["total"] == [30, 30]
    p.procesar("en 2$ le dejo el transporte")
    cita = repo.obtener_cita(cid)
    assert cita["cotizacion"]["total"] == [27, 27]
    assert "27.00$" in mensajes.resumen_para_propietaria(cita)


def test_varias_pendientes_sin_cita_referenciada_pide_aclarar():
    p, repo, _ = _procesador()
    a, b = _cita(repo), _cita(repo)
    resp = p.procesar("listo")
    assert f"#{a}" in resp and f"#{b}" in resp
    assert repo.obtener_cita(a)["estado"] == "pendiente_aprobacion"


def test_pico_y_placa_bloquea_puerta_a_puerta_pero_no_salon():
    jueves_17 = JUEVES_10.replace(hour=17)
    ok, motivo = validar_horario(jueves_17, 60, "puerta_a_puerta", MOTOR, CFG)
    assert not ok and "restricción" in motivo
    assert validar_horario(jueves_17, 60, "salon", MOTOR, CFG)[0]
    alternativas = proponer_alternativas(jueves_17, 60, "puerta_a_puerta", MOTOR, CFG)
    assert alternativas and all(a.hour < 16 or a.date() != jueves_17.date() for a in alternativas)


def test_confirmacion_incluye_total_y_traslado():
    p, repo, msj = _procesador()
    cid = _cita(repo)
    p.procesar("listo", id_citado=f"wamid.cita{cid}")
    [confirmacion] = msj.a(CLI)
    assert "Baño Completo" in confirmacion
    assert "30.00$ con el servicio puerta a puerta incluido" in confirmacion
