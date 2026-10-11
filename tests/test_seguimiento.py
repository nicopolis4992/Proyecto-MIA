"""SCRUM-76: recordatorios a la propietaria y solicitudes vencidas."""

from datetime import timedelta

from test_aprobacion import CLI, JUEVES_10, PROP, _cita, _procesador

from app.agenda.seguimiento import revisar


def _enviada(repo, cid, cuando):
    repo.registrar_evento(cid, "enviada_a_propietaria")
    repo._ejecutar("UPDATE eventos_cita SET fecha = ? WHERE cita_id = ?", (cuando.isoformat(), cid))


def test_recordatorios_luego_aviso_al_cliente_y_nada_mas():
    p, repo, msj = _procesador()
    cid = _cita(repo)
    envio = JUEVES_10 - timedelta(days=1)  # miercoles 10:00, la cita es el jueves 10:00
    _enviada(repo, cid, envio)

    assert revisar(p, envio + timedelta(minutes=30))["recordatorios"] == 0  # aun no toca
    pasos = [envio + timedelta(minutes=m) for m in (50, 100, 150, 200)]
    for momento in pasos:
        # El evento del recordatorio se fecha con el reloj real: se ajusta al momento simulado.
        revisar(p, momento)
        repo._ejecutar("UPDATE eventos_cita SET fecha = ? WHERE cita_id = ? AND fecha > ?",
                       (momento.isoformat(), cid, momento.isoformat()))
    recordatorios = [t for t in msj.a(PROP) if "Recordatorio" in t]
    assert len(recordatorios) == 2 and "#%d" % cid in recordatorios[0]
    assert msj.a(CLI) == [msj.a(CLI)[0]] and "sigue en revisión" in msj.a(CLI)[0]
    # Citar el recordatorio sirve para aprobar.
    assert repo.obtener_cita(cid)["msg_aprobacion_id"] != f"wamid.cita{cid}"


def test_no_se_le_escribe_de_madrugada():
    p, repo, msj = _procesador()
    cid = _cita(repo)
    madrugada = JUEVES_10.replace(hour=2) - timedelta(days=1)
    _enviada(repo, cid, madrugada - timedelta(hours=2))
    assert revisar(p, madrugada)["recordatorios"] == 0
    assert msj.a(PROP) == []


def test_vence_si_la_cita_esta_por_empezar_y_ofrece_otros_horarios():
    p, repo, msj = _procesador()
    cid = _cita(repo)
    _enviada(repo, cid, JUEVES_10 - timedelta(hours=3))
    assert revisar(p, JUEVES_10 - timedelta(minutes=40))["vencidas"] == 1
    assert repo.obtener_cita(cid)["estado"] == "rechazada"
    assert "vencida" in [e["tipo"] for e in repo.eventos_de_cita(cid)]
    assert "venció sin respuesta" in msj.a(PROP)[-1]
    assert repo.obtener_sesion(CLI)["flujo"] == "agendando"


def test_sin_envio_a_la_propietaria_no_hay_seguimiento():
    p, repo, msj = _procesador()
    _cita(repo)
    assert revisar(p, JUEVES_10 - timedelta(days=1)) == {"recordatorios": 0, "clientes_avisados": 0, "vencidas": 0}
