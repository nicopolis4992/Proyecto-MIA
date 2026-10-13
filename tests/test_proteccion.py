"""Cifrado de datos personales en la base del piloto y purga de datos operativos (LOPDP)."""

import sqlite3
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet

from app.config import ahora
from app.persistencia.proteccion import Proteccion
from app.persistencia.repositorio import Repositorio

TEL, NOMBRE = "593991234567", "María Pérez"
SEUD = "x" * 40
CLAVE = Fernet.generate_key().decode()


def _proteccion(*claves):
    return Proteccion(list(claves or [CLAVE]), SEUD)


def _crudo(ruta) -> str:
    """Todo el contenido del archivo de la base, tal como lo vería quien lo copie."""
    con = sqlite3.connect(ruta)
    filas = []
    for (tabla,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        filas += [str(f) for f in con.execute(f"SELECT * FROM {tabla}")]
    con.close()
    return "\n".join(filas)


def _poblar(repo):
    cid = repo.crear_cita(cliente_telefono=TEL, cliente_nombre=NOMBRE, referido_por="Ana",
                          mascotas=[{"nombre": "Luna"}], modalidad="salon", estado="confirmada")
    repo.registrar_evento(cid, "respuesta_propietaria", {"texto": f"listo, avísale a {NOMBRE}"})
    repo.guardar_sesion(TEL, {"reserva": {"cliente_nombre": NOMBRE}})
    repo.encolar_mensaje(TEL, f"Hola {NOMBRE}, su cita…", "caida")
    repo.marcar_mensaje(1, "esperando_ventana")
    repo.pausar_bot(True)
    return cid


def test_en_el_archivo_no_hay_telefonos_ni_nombres_pero_la_app_los_lee(tmp_path):
    ruta = tmp_path / "piloto.sqlite3"
    repo = Repositorio(ruta, _proteccion())
    cid = _poblar(repo)

    crudo = _crudo(ruta)
    assert TEL not in crudo and NOMBRE not in crudo and "Ana" not in crudo

    cita = repo.obtener_cita(cid)
    assert (cita["cliente_telefono"], cita["cliente_nombre"], cita["referido_por"]) == (TEL, NOMBRE, "Ana")
    assert "cliente_clave" not in cita
    assert NOMBRE in repo.eventos_de_cita(cid)[-1]["detalle"]["texto"]
    assert repo.obtener_sesion(TEL)["reserva"]["cliente_nombre"] == NOMBRE
    assert repo.citas_previas(TEL) == 1                      # busqueda por seudonimo
    [m] = repo.mensajes_en_espera(TEL)
    assert m["destino"] == TEL and NOMBRE in m["cuerpo"]
    assert repo.bot_pausado()


def test_una_base_existente_se_cifra_al_activar_las_claves(tmp_path):
    ruta = tmp_path / "vieja.sqlite3"
    cid = _poblar(Repositorio(ruta, Proteccion()))           # sin claves: en claro
    assert TEL in _crudo(ruta)

    repo = Repositorio(ruta, _proteccion())                 # se activan las claves
    assert TEL not in _crudo(ruta) and NOMBRE not in _crudo(ruta)
    assert repo.obtener_cita(cid)["cliente_telefono"] == TEL
    assert repo.obtener_sesion(TEL)["reserva"]["cliente_nombre"] == NOMBRE
    assert repo.citas_previas(TEL) == 1 and repo.bot_pausado()
    Repositorio(ruta, _proteccion())                         # migrar dos veces no rompe nada
    assert repo.obtener_cita(cid)["cliente_nombre"] == NOMBRE


def test_sin_las_claves_no_se_puede_leer_lo_cifrado(tmp_path):
    ruta = tmp_path / "piloto.sqlite3"
    cid = _poblar(Repositorio(ruta, _proteccion()))
    with pytest.raises(RuntimeError, match="faltan las claves"):
        Repositorio(ruta, Proteccion()).obtener_cita(cid)


def test_rotacion_de_claves(tmp_path):
    ruta = tmp_path / "piloto.sqlite3"
    cid = _poblar(Repositorio(ruta, _proteccion(CLAVE)))
    nueva = Fernet.generate_key().decode()
    repo = Repositorio(ruta, _proteccion(nueva, CLAVE))      # la nueva primero, la vieja para leer
    assert repo.obtener_cita(cid)["cliente_nombre"] == NOMBRE


def test_purga_borra_lo_operativo_viejo_y_conserva_citas_y_estado_del_bot():
    repo = Repositorio(":memory:", _proteccion())
    cid = _poblar(repo)
    repo.guardar_sesion("593900000002", {"x": 1})            # sesion reciente
    repo.marcar_procesado("wamid.viejo")
    viejo = (ahora() - timedelta(days=40)).isoformat(timespec="seconds")
    for tabla, col in (("sesiones", "actualizada"), ("mensajes_procesados", "fecha"), ("mensajes_salientes", "actualizado")):
        repo._ejecutar(f"UPDATE {tabla} SET {col} = ?", (viejo,))
    repo.guardar_sesion("593900000002", {"x": 2})            # vuelve a ser reciente

    borradas = repo.purgar()
    assert borradas == {"sesiones": 1, "mensajes_procesados": 1, "mensajes_salientes": 1}
    assert repo.obtener_sesion(TEL) == {} and repo.obtener_sesion("593900000002") == {"x": 2}
    assert repo.bot_pausado()                                # el interruptor no se purga
    assert repo.obtener_cita(cid) is not None                # las citas se conservan
