"""Pruebas de la versión para Supabase: flujo del prototipo y endurecimiento.

SB1  Las migraciones corren sin superusuario y los objetos quedan a nombre de mia_duenio.
SB2  Los roles de la API de Supabase (anon, authenticated) no ven nada.
SB3  RLS activo en todas las tablas.
SB4  Flujo del prototipo: la propietaria propone un cambio y el cliente lo acepta.
SB5  El agente sigue sin poder aprobar nada que la propietaria no haya visto.
SB6  Reprogramación: el cliente pide otro horario y vuelve a la propietaria.
SB7  Cancelación por el cliente.
SB8  Estado operativo (sesiones, cola de salida, deduplicación) y purga.
SB9  Catálogos del tarifario v2 y datos operativos de la cita.
SB10 La restricción vehicular (SCRUM-73) está disponible para el agente.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import psycopg
import pytest

from mia_agenda import Descuento, Linea, Mascota

from .test_scrum74 import cot, estado, propuesta, registrar

D = Decimal


def _proponer(bd, cita_id, version=1, cambios='{"lineas": [{"linea": 1, "precio_estimado": "17.00"}]}', texto="a 17 por las motas"):
    return bd("aprobacion").execute(
        "SELECT mia.fn_proponer_al_cliente(%s, %s, %s::jsonb, %s)", (cita_id, version, cambios, texto)
    ).fetchone()[0]


# ─────────────────────────────── SB1 ───────────────────────────────
def test_SB1_los_objetos_pertenecen_a_mia_duenio_y_no_al_usuario_de_migraciones(bd):
    duenos = {f[0] for f in bd("admin").execute("""
        SELECT DISTINCT pg_get_userbyid(c.relowner) FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname IN ('mia', 'mia_op', 'mia_rv') AND c.relkind IN ('r', 'v')""")}
    assert duenos == {"mia_duenio"}
    funciones = {f[0] for f in bd("admin").execute("""
        SELECT DISTINCT pg_get_userbyid(p.proowner) FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname IN ('mia', 'mia_op')""")}
    assert funciones == {"mia_duenio"}


# ─────────────────────────────── SB2 ───────────────────────────────
@pytest.mark.parametrize("rol", ["anon", "authenticated"])
@pytest.mark.parametrize("consulta", [
    "SELECT * FROM mia.cita", "SELECT * FROM mia.v_cita_resumen", "SELECT * FROM mia_op.sesion",
    "SELECT * FROM mia_rv.franja", "SELECT mia.fn_cambiar_estado(1, 1, 'aprobada')",
])
def test_SB2_los_roles_de_la_api_no_tienen_acceso(bd, rol, consulta):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        bd(rol).execute(consulta)


# ─────────────────────────────── SB3 ───────────────────────────────
def test_SB3_rls_activo_en_todas_las_tablas(bd):
    sin_rls = bd("admin").execute("""
        SELECT n.nspname || '.' || c.relname FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname IN ('mia', 'mia_op', 'mia_rv') AND c.relkind = 'r' AND NOT c.relrowsecurity""").fetchall()
    assert sin_rls == []


def test_SB3_con_rls_los_servicios_siguen_funcionando(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    assert bd("agente").execute("SELECT count(*) FROM mia.servicio").fetchone()[0] > 0
    assert bd("lectura").execute("SELECT count(*) FROM mia.cita_evento WHERE cita_id = %s",
                                 (r.cita_id,)).fetchone()[0] == 1


# ─────────────────────────────── SB4 ───────────────────────────────
def test_SB4_la_propietaria_propone_un_cambio_y_el_cliente_lo_acepta(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    nueva = _proponer(bd, r.cita_id, cambios='{"lineas": [{"linea": 1, "precio_estimado": "18.00"}]}')
    assert nueva == 2
    assert estado(bd, r.cita_id) == ("propuesta_cliente", 2)
    # El cliente acepta a través del agente: la cita queda aprobada…
    bd("agente").execute("SELECT mia.fn_cambiar_estado(%s, 2, 'aprobada', 'sí, dale')", (r.cita_id,))
    assert estado(bd, r.cita_id) == ("aprobada", 2)
    # …y solo el sistema la confirma, después de avisarle.
    bd("sistema").execute("SELECT mia.fn_cambiar_estado(%s, 2, 'confirmada')", (r.cita_id,))
    eventos = bd("admin").execute(
        "SELECT estado_nuevo::text, actor::text FROM mia.cita_evento WHERE cita_id = %s ORDER BY evento_id",
        (r.cita_id,)).fetchall()
    assert eventos == [("pendiente_aprobacion", "agente"), ("propuesta_cliente", "propietaria"),
                       ("aprobada", "cliente"), ("confirmada", "sistema")]


def test_SB4_aceptar_una_version_que_la_propietaria_ya_cambio_falla(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    _proponer(bd, r.cita_id)
    with pytest.raises(psycopg.errors.SerializationFailure):
        bd("agente").execute("SELECT mia.fn_cambiar_estado(%s, 1, 'aprobada')", (r.cita_id,))


def test_SB4_la_propuesta_al_cliente_queda_registrada_con_su_foto(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    _proponer(bd, r.cita_id, cambios='{"lineas": [{"linea": 1, "precio_estimado": "18.00"}]}')
    foto = bd("admin").execute("""SELECT foto_propuesta FROM mia.cita_evento
                                  WHERE cita_id = %s AND estado_nuevo = 'propuesta_cliente'""",
                               (r.cita_id,)).fetchone()[0]
    assert foto["version"] == 2 and foto["lineas"][0]["precio_estimado"] == 18.0


# ─────────────────────────────── SB5 ───────────────────────────────
def test_SB5_el_agente_no_puede_proponer_en_nombre_de_la_propietaria(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        bd("agente").execute("SELECT mia.fn_proponer_al_cliente(%s, 1, '{}'::jsonb)", (r.cita_id,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        bd("agente").execute("SELECT mia.fn_cambiar_estado(%s, 1, 'aprobada')", (r.cita_id,))
    assert estado(bd, r.cita_id) == ("pendiente_aprobacion", 1)


def test_SB5_las_transiciones_que_cambian_la_propuesta_exigen_su_funcion(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    with pytest.raises(psycopg.errors.CheckViolation, match="fn_proponer_al_cliente"):
        bd("aprobacion").execute("SELECT mia.fn_cambiar_estado(%s, 1, 'propuesta_cliente')", (r.cita_id,))


def test_SB5_todo_camino_a_aprobada_pasa_por_la_propietaria(bd):
    """Invariante del grafo de estados: a «aprobada» solo se llega por una
    decisión de la propietaria, directa o propuesta por ella al cliente."""
    t = bd("admin").execute("SELECT desde::text, hacia::text, rol_requerido FROM mia.transicion_estado").fetchall()
    for desde, hacia, rol in t:
        if hacia == "aprobada":
            assert rol == "mia_aprobacion" or desde == "propuesta_cliente", (desde, hacia, rol)
        if hacia == "propuesta_cliente":
            assert rol == "mia_aprobacion"
        if hacia == "confirmada":
            assert (desde, rol) == ("aprobada", "mia_sistema")


# ─────────────────────────────── SB6 ───────────────────────────────
def test_SB6_reprogramar_vuelve_a_la_propietaria_con_version_nueva(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    bd("aprobacion").execute("SELECT mia.fn_cambiar_estado(%s, 1, 'aprobada')", (r.cita_id,))
    bd("sistema").execute("SELECT mia.fn_cambiar_estado(%s, 1, 'confirmada')", (r.cita_id,))
    ag = bd("agente")
    ag.execute("SELECT mia.fn_cambiar_estado(%s, 1, 'en_reprogramacion', 'mejor otro día')", (r.cita_id,))
    nuevo = manana_10h + timedelta(days=1)
    v = ag.execute("SELECT mia.fn_reprogramar(%s, 1, %s, %s, 'el jueves a las 10')",
                   (r.cita_id, nuevo, nuevo + timedelta(hours=2))).fetchone()[0]
    assert v == 2
    assert estado(bd, r.cita_id) == ("pendiente_aprobacion", 2)
    # Y la propietaria vuelve a decidir.
    bd("aprobacion").execute("SELECT mia.fn_cambiar_estado(%s, 2, 'aprobada')", (r.cita_id,))


def test_SB6_reprogramar_libera_el_horario_anterior(bd, claves, manana_10h):
    a = registrar(bd, claves, propuesta(manana_10h, clave="wamid.A"))
    bd("aprobacion").execute("SELECT mia.fn_cambiar_estado(%s, 1, 'aprobada')", (a.cita_id,))
    bd("agente").execute("SELECT mia.fn_cambiar_estado(%s, 1, 'en_reprogramacion')", (a.cita_id,))
    b = registrar(bd, claves, propuesta(manana_10h, clave="wamid.B", telefono_solicitante="0987654321"))
    bd("aprobacion").execute("SELECT mia.fn_cambiar_estado(%s, 1, 'aprobada')", (b.cita_id,))  # no choca
    assert estado(bd, b.cita_id)[0] == "aprobada"


def test_SB6_no_se_reprograma_una_cita_que_no_lo_pidio(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    with pytest.raises(psycopg.errors.CheckViolation, match="en_reprogramacion"):
        bd("agente").execute("SELECT mia.fn_reprogramar(%s, 1, %s, %s)",
                             (r.cita_id, manana_10h, manana_10h + timedelta(hours=1)))


# ─────────────────────────────── SB7 ───────────────────────────────
def test_SB7_el_cliente_cancela_y_la_cita_no_se_borra(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    bd("agente").execute("SELECT mia.fn_cambiar_estado(%s, 1, 'cancelada', 'ya no puedo')", (r.cita_id,))
    assert estado(bd, r.cita_id)[0] == "cancelada"
    with pytest.raises(psycopg.errors.CheckViolation):
        bd("aprobacion").execute("SELECT mia.fn_cambiar_estado(%s, 1, 'aprobada')", (r.cita_id,))


# ─────────────────────────────── SB8 ───────────────────────────────
def test_SB8_sesiones_cola_y_deduplicacion(bd):
    ag = bd("agente")
    ag.execute("INSERT INTO mia_op.sesion (telefono_hmac, datos) VALUES (repeat('a', 64), '{\"flujo\": \"agendando\"}')")
    ag.execute("""INSERT INTO mia_op.sesion (telefono_hmac, datos) VALUES (repeat('a', 64), '{"flujo": "ninguno"}')
                  ON CONFLICT (telefono_hmac) DO UPDATE SET datos = excluded.datos, actualizada = now()""")
    assert ag.execute("SELECT datos->>'flujo' FROM mia_op.sesion").fetchone()[0] == "ninguno"
    ag.execute("INSERT INTO mia_op.mensaje_procesado (wa_id) VALUES ('wamid.1')")
    with pytest.raises(psycopg.errors.UniqueViolation):
        ag.execute("INSERT INTO mia_op.mensaje_procesado (wa_id) VALUES ('wamid.1')")
    ag.execute("INSERT INTO mia_op.mensaje_saliente (destino_cifrado, cuerpo_cifrado, ultimo_error) "
               "VALUES ('\\x01', '\\x02', 'timeout')")
    bd("sistema").execute("UPDATE mia_op.mensaje_saliente SET estado = 'enviado', intentos = intentos + 1")


def test_SB8_la_sesion_no_guarda_el_telefono_en_claro(bd):
    with pytest.raises(psycopg.errors.CheckViolation):
        bd("agente").execute("INSERT INTO mia_op.sesion (telefono_hmac) VALUES ('0991234567')")


def test_SB8_purga_de_datos_operativos(bd):
    adm = bd("admin")
    adm.execute("INSERT INTO mia_op.sesion (telefono_hmac, actualizada) VALUES (repeat('b', 64), now() - interval '40 days')")
    adm.execute("INSERT INTO mia_op.mensaje_procesado (wa_id, fecha) VALUES ('viejo', now() - interval '10 days')")
    fila = bd("sistema").execute("SELECT * FROM mia_op.fn_purgar_operacion()").fetchone()
    assert fila[:2] == (1, 1)
    with pytest.raises(psycopg.errors.CheckViolation):
        bd("sistema").execute("SELECT * FROM mia_op.fn_purgar_operacion(30, 1)")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        bd("agente").execute("SELECT * FROM mia_op.fn_purgar_operacion()")


# ─────────────────────────────── SB9 ───────────────────────────────
def test_SB9_servicios_y_descuentos_del_tarifario_v2(bd, claves, manana_10h):
    p = propuesta(manana_10h, lineas=(
        Linea(Mascota("Tita", "Shih tzu", "tranquilo"), "completo", cot("15.00")),
        Linea(Mascota("Coco", "Pug", "tranquilo"), "deslanado", cot("12.00")),
    ), descuento=Descuento("multi_mascota", "dos perros", D("2.00")), tarifario_version="v2",
        sector="Cotocollao", pedido_especial="sin perfume", requiere_revision_manual=True)
    r = registrar(bd, claves, p)
    fila = bd("lectura").execute("""SELECT n_mascotas, total_estimado, descuento_tipo, sector, pedido_especial,
                                           requiere_revision_manual FROM mia.v_cita_resumen WHERE cita_id = %s""",
                                 (r.cita_id,)).fetchone()
    assert fila == (2, D("25.00"), "multi_mascota", "Cotocollao", "sin perfume", True)


def test_SB9_el_wamid_del_resumen_se_guarda_sin_cambiar_la_version(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    bd("agente").execute("SELECT mia.fn_marcar_enviada_a_propietaria(%s, 'wamid.RESUMEN')", (r.cita_id,))
    fila = bd("agente").execute("SELECT cita_id, version FROM mia.v_cita_resumen WHERE msg_aprobacion_id = 'wamid.RESUMEN'").fetchone()
    assert fila == (r.cita_id, 1)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        bd("lectura").execute("SELECT mia.fn_marcar_enviada_a_propietaria(%s, 'x')", (r.cita_id,))


def test_SB9_un_desenredo_largo_cabe_en_el_horario(bd, claves, manana_10h):
    p = propuesta(manana_10h, fin=manana_10h + timedelta(hours=10))
    assert registrar(bd, claves, p).creada


# ─────────────────────────────── SB10 ──────────────────────────────
def test_SB10_restriccion_vehicular_disponible_para_el_agente(bd):
    ag = bd("agente")
    assert ag.execute("SELECT count(*) FROM mia_rv.franja").fetchone()[0] == 2
    assert ag.execute("SELECT dia_iso FROM mia_rv.digito_dia WHERE digito = 7").fetchone()[0] == 4
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        ag.execute("UPDATE mia_rv.franja SET fin = '10:00'")
