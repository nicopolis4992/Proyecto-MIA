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
            "eligio_alternativa": None, "cancelar": False}
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
