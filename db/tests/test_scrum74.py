"""Pruebas de SCRUM-74, nombradas por criterio de aceptación (CA).

CA1  La cita queda persistida con estado «pendiente de aprobación».
CA2  Nada puede saltarse la aprobación de la propietaria (human-in-the-loop).
CA3  Varias mascotas en una cita con total agregado; traslado una vez por visita.
CA4  Referidos: un contacto agenda para terceros.
CA5  Idempotencia ante reintentos de WhatsApp.
CA6  Lo que se aprueba es exactamente lo que se confirma (versiones).
CA7  Dos citas aprobadas no se solapan; dos pendientes sí pueden coincidir.
CA8  Privacidad: ningún dato de contacto en claro en la base (LOPDP).
CA9  Historial completo e inmutable.
CA10 Reparto de ingresos configurable y versionado.
CA11 Integridad de montos y datos.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import psycopg
import pytest

from mia_agenda import (
    Cotizacion, Descuento, Linea, Mascota, PropuestaCita, PropuestaInvalida, Tercero,
    normalizar_telefono, obtener_resumen, registrar_cita_propuesta,
)

TEL = "0991234567"          # número ficticio
D = Decimal


def cot(precio: str, semi: str = "0", comprometido: bool = True, faltan=()) -> Cotizacion:
    return Cotizacion(precio_estimado=D(precio), semiamplitud=D(semi),
                      es_comprometido=comprometido, atributos_no_declarados=tuple(faltan),
                      desglose={"fuente": "prueba"})


def propuesta(inicio, clave="wamid.PRUEBA-1", **cambios) -> PropuestaCita:
    base = PropuestaCita(
        clave_idempotencia=clave,
        telefono_solicitante=TEL,
        nombre_solicitante="Clienta Ficticia",
        origen="LINAS",
        inicio=inicio,
        fin=inicio + timedelta(hours=2),
        lineas=(Linea(Mascota("Tita", "Poodle", "tranquilo"), "SB", cot("15.00")),),
        tarifario_version="v1",
    )
    return replace(base, **cambios)


def registrar(bd, claves, p):
    seud, cif = claves
    return registrar_cita_propuesta(bd("agente"), p, seud, cif)


def estado(bd, cita_id):
    return bd("admin").execute("SELECT estado, version FROM mia.cita WHERE cita_id = %s", (cita_id,)).fetchone()


# ─────────────────────────────── CA1 ───────────────────────────────
def test_CA1_la_cita_se_registra_pendiente_de_aprobacion(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    assert r.creada
    assert estado(bd, r.cita_id) == ("pendiente_aprobacion", 1)


def test_CA1_no_se_puede_insertar_directamente_como_confirmada(bd, manana_10h):
    admin = bd("admin")   # ni siquiera un administrador
    with pytest.raises(psycopg.errors.CheckViolation, match="pendiente_aprobacion"):
        admin.execute("""
            INSERT INTO mia.cliente (identificador_hmac, tipo_identificador, telefono_cifrado, nombre_cifrado)
            VALUES (repeat('a', 64), 'telefono', '\\x00', '\\x00');
            INSERT INTO mia.cita (solicitante_id, origen_codigo, horario_propuesto, estado,
                                  tarifario_version, clave_idempotencia)
            VALUES (1, 'LINAS', tstzrange(now() + interval '1 day', now() + interval '1 day 2 hours'),
                    'confirmada', 'v1', 'x');""")


def test_CA1_no_se_registran_horarios_pasados(bd, claves, manana_10h):
    with pytest.raises(psycopg.errors.CheckViolation, match="ya pasó"):
        registrar(bd, claves, propuesta(manana_10h - timedelta(days=5)))


# ─────────────────────────────── CA2 ───────────────────────────────
def test_CA2_el_agente_no_puede_aprobar_ni_confirmar(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    agente = bd("agente")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        agente.execute("SELECT mia.fn_cambiar_estado(%s, 1, 'aprobada')", (r.cita_id,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        agente.execute("UPDATE mia.cita SET estado = 'aprobada' WHERE cita_id = %s", (r.cita_id,))
    assert estado(bd, r.cita_id)[0] == "pendiente_aprobacion"


def test_CA2_no_existe_atajo_de_pendiente_a_confirmada(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    with pytest.raises(psycopg.errors.CheckViolation, match="Transición no permitida"):
        bd("sistema").execute("SELECT mia.fn_cambiar_estado(%s, 1, 'confirmada')", (r.cita_id,))
    with pytest.raises(psycopg.errors.CheckViolation, match="Transición no permitida"):
        bd("admin").execute("UPDATE mia.cita SET estado = 'confirmada' WHERE cita_id = %s", (r.cita_id,))


def test_CA2_camino_completo_aprobada_y_luego_confirmada(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    bd("aprobacion").execute("SELECT mia.fn_cambiar_estado(%s, 1, 'aprobada', 'dale nomas')", (r.cita_id,))
    bd("sistema").execute("SELECT mia.fn_cambiar_estado(%s, 1, 'confirmada')", (r.cita_id,))
    assert estado(bd, r.cita_id) == ("confirmada", 1)


def test_CA2_el_canal_de_aprobacion_no_puede_marcar_confirmada(bd, claves, manana_10h):
    """Confirmar es posterior a avisar al cliente (SCRUM-78): lo hace el sistema."""
    r = registrar(bd, claves, propuesta(manana_10h))
    ap = bd("aprobacion")
    ap.execute("SELECT mia.fn_cambiar_estado(%s, 1, 'aprobada')", (r.cita_id,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        ap.execute("SELECT mia.fn_cambiar_estado(%s, 1, 'confirmada')", (r.cita_id,))


def test_CA2_expiracion_por_falta_de_respuesta(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    bd("sistema").execute("SELECT mia.fn_cambiar_estado(%s, 1, 'expirada', 'sin respuesta tras 3 recordatorios')", (r.cita_id,))
    assert estado(bd, r.cita_id)[0] == "expirada"
    with pytest.raises(psycopg.errors.CheckViolation):
        bd("aprobacion").execute("SELECT mia.fn_cambiar_estado(%s, 1, 'aprobada')", (r.cita_id,))


# ─────────────────────────────── CA3 ───────────────────────────────
def test_CA3_varias_mascotas_con_total_agregado_caso_real(bd, claves, manana_10h):
    """Caso del chat: «25$ de Tita y Cube, y 12$ de Thomas. Total: 37$» + 2$ de transporte."""
    p = propuesta(
        manana_10h,
        lineas=(
            Linea(Mascota("Tita"), "SB", cot("12.50")),
            Linea(Mascota("Cube"), "SB", cot("12.50")),
            Linea(Mascota("Thomas"), "SC", cot("12.00")),
        ),
        puerta_a_puerta=True, costo_traslado=D("2.00"),
        direccion="Calle ficticia 123", dentro_perimetro_urbano=False,
    )
    r = registrar(bd, claves, p)
    res = obtener_resumen(bd("lectura"), r.cita_id)
    assert res["n_mascotas"] == 3
    assert res["subtotal_servicios"] == D("37.00")
    assert res["costo_traslado"] == D("2.00")
    assert res["total_estimado"] == D("39.00")


def test_CA3_traslado_se_cobra_una_vez_por_visita(bd, claves, manana_10h):
    """La estructura lo impide: el traslado no existe a nivel de mascota."""
    columnas = {c for (c,) in bd("admin").execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'mia' AND table_name = 'cita_linea'")}
    assert not any("traslado" in c for c in columnas)


def test_CA3_la_banda_de_confianza_se_conserva(bd, claves, manana_10h):
    p = propuesta(manana_10h, lineas=(
        Linea(Mascota("Luna"), "SB", cot("24.00", "6.00", False, ("tamano", "estado_manto"))),
        Linea(Mascota("Max"), "SB", cot("20.50", "0.50", True)),
    ))
    r = registrar(bd, claves, p)
    res = obtener_resumen(bd("lectura"), r.cita_id)
    assert res["total_semiamplitud"] == D("6.50")
    assert res["total_comprometido"] is False
    faltan = bd("admin").execute(
        "SELECT atributos_no_declarados FROM mia.cita_linea WHERE cita_id = %s AND linea = 1", (r.cita_id,)).fetchone()[0]
    assert faltan == ["tamano", "estado_manto"]


# ─────────────────────────────── CA4 ───────────────────────────────
def test_CA4_un_contacto_agenda_para_su_prima_sin_telefono(bd, claves, manana_10h):
    p = propuesta(manana_10h, lineas=(
        Linea(Mascota("Tita"), "SB", cot("12.50")),
        Linea(Mascota("Rocky", duenio=Tercero("Prima Ficticia")), "SB", cot("15.00")),
    ))
    r = registrar(bd, claves, p)
    filas = bd("admin").execute("""
        SELECT m.nombre, cl.tipo_identificador, cl.referido_por = c.solicitante_id OR cl.cliente_id = c.solicitante_id
          FROM mia.cita_linea l JOIN mia.mascota m USING (mascota_id)
          JOIN mia.cliente cl ON cl.cliente_id = m.propietario_id
          JOIN mia.cita c ON c.cita_id = l.cita_id
         WHERE l.cita_id = %s ORDER BY l.linea""", (r.cita_id,)).fetchall()
    assert filas == [("Tita", "telefono", True), ("Rocky", "tercero", True)]


def test_CA4_el_mismo_tercero_se_reconoce_en_la_siguiente_cita(bd, claves, manana_10h):
    l = Linea(Mascota("Rocky", duenio=Tercero("Prima  Fícticia")), "SB", cot("15.00"))
    registrar(bd, claves, propuesta(manana_10h, lineas=(l,)))
    l2 = Linea(Mascota("rocky", duenio=Tercero("prima ficticia")), "SB", cot("15.00"))
    registrar(bd, claves, propuesta(manana_10h + timedelta(days=7), clave="wamid.PRUEBA-2", lineas=(l2,)))
    admin = bd("admin")
    assert admin.execute("SELECT count(*) FROM mia.mascota").fetchone()[0] == 1
    assert admin.execute("SELECT count(*) FROM mia.cliente WHERE tipo_identificador = 'tercero'").fetchone()[0] == 1


def test_CA4_quien_recomienda_queda_registrado(bd, claves, manana_10h):
    registrar(bd, claves, propuesta(manana_10h, clave="w-ref", telefono_solicitante="0987654321",
                                    nombre_solicitante="Vecina Ficticia"))
    r = registrar(bd, claves, propuesta(manana_10h + timedelta(days=1), telefono_referente="+593 98 765 4321",
                                        descuento=Descuento("referido", "puerta a puerta gratuito por referido")))
    ref = bd("admin").execute("""
        SELECT r.cliente_id IS NOT NULL FROM mia.cita c JOIN mia.cliente s ON s.cliente_id = c.solicitante_id
          LEFT JOIN mia.cliente r ON r.cliente_id = s.referido_por WHERE c.cita_id = %s""", (r.cita_id,)).fetchone()[0]
    assert ref is True


# ─────────────────────────────── CA5 ───────────────────────────────
def test_CA5_el_reintento_del_mismo_mensaje_no_duplica(bd, claves, manana_10h):
    p = propuesta(manana_10h)
    r1 = registrar(bd, claves, p)
    r2 = registrar(bd, claves, p)       # Meta reenvía el webhook
    assert r1.cita_id == r2.cita_id and r1.creada and not r2.creada
    admin = bd("admin")
    assert admin.execute("SELECT count(*) FROM mia.cita").fetchone()[0] == 1
    assert admin.execute("SELECT count(*) FROM mia.cita_evento").fetchone()[0] == 1


def test_CA5_formatos_distintos_del_mismo_numero_son_un_solo_cliente(bd, claves, manana_10h):
    for i, tel in enumerate(["0991234567", "+593 99 123 4567", "593991234567", "(099) 123-4567"]):
        registrar(bd, claves, propuesta(manana_10h + timedelta(days=i), clave=f"w{i}", telefono_solicitante=tel))
    assert bd("admin").execute("SELECT count(*) FROM mia.cliente").fetchone()[0] == 1


# ─────────────────────────────── CA6 ───────────────────────────────
def test_CA6_modificar_y_reproponer_sube_la_version(bd, claves, manana_10h):
    """«a las 12 estaría bien» / «en 2$ le dejo el transporte»."""
    r = registrar(bd, claves, propuesta(manana_10h))
    nueva = bd("aprobacion").execute(
        "SELECT mia.fn_reproponer(%s, 1, %s::jsonb, 'a las 12 estaría bien')",
        (r.cita_id, '{"horario_inicio": "%s", "horario_fin": "%s"}' % (
            (manana_10h + timedelta(hours=2)).isoformat(), (manana_10h + timedelta(hours=4)).isoformat()))
    ).fetchone()[0]
    assert nueva == 2
    assert estado(bd, r.cita_id) == ("pendiente_aprobacion", 2)


def test_CA6_aprobar_una_version_obsoleta_falla(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    ap = bd("aprobacion")
    ap.execute("SELECT mia.fn_reproponer(%s, 1, '{\"lineas\": [{\"linea\": 1, \"precio_estimado\": \"13.00\"}]}'::jsonb)",
               (r.cita_id,))
    with pytest.raises(psycopg.errors.SerializationFailure, match="obsoleta"):
        ap.execute("SELECT mia.fn_cambiar_estado(%s, 1, 'aprobada')", (r.cita_id,))


def test_CA6_una_cita_aprobada_queda_congelada(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    bd("aprobacion").execute("SELECT mia.fn_cambiar_estado(%s, 1, 'aprobada')", (r.cita_id,))
    admin = bd("admin")
    with pytest.raises(psycopg.errors.CheckViolation):
        admin.execute("UPDATE mia.cita_linea SET precio_estimado = 1 WHERE cita_id = %s", (r.cita_id,))
    with pytest.raises(psycopg.errors.CheckViolation):
        admin.execute("UPDATE mia.cita SET costo_traslado = 0, descuento_monto = 5 WHERE cita_id = %s", (r.cita_id,))


# ─────────────────────────────── CA7 ───────────────────────────────
def test_CA7_dos_pendientes_pueden_pedir_la_misma_hora(bd, claves, manana_10h):
    registrar(bd, claves, propuesta(manana_10h, clave="a"))
    registrar(bd, claves, propuesta(manana_10h, clave="b", telefono_solicitante="0987654321"))
    assert bd("admin").execute("SELECT count(*) FROM mia.cita").fetchone()[0] == 2


def test_CA7_no_se_aprueban_dos_citas_solapadas(bd, claves, manana_10h):
    a = registrar(bd, claves, propuesta(manana_10h, clave="a"))
    b = registrar(bd, claves, propuesta(manana_10h + timedelta(hours=1), clave="b", telefono_solicitante="0987654321"))
    ap = bd("aprobacion")
    ap.execute("SELECT mia.fn_cambiar_estado(%s, 1, 'aprobada')", (a.cita_id,))
    with pytest.raises(psycopg.errors.ExclusionViolation):
        ap.execute("SELECT mia.fn_cambiar_estado(%s, 1, 'aprobada')", (b.cita_id,))


# ─────────────────────────────── CA8 ───────────────────────────────
def test_CA8_ningun_dato_de_contacto_en_claro(bd, claves, manana_10h):
    p = propuesta(manana_10h, nombre_solicitante="Nombre Muy Reconocible",
                  puerta_a_puerta=True, costo_traslado=D("3.00"),
                  direccion="Av. Ficticia N45-67 y Calle Inventada", dentro_perimetro_urbano=True)
    registrar(bd, claves, p)
    volcado = bd("admin").execute("""
        SELECT string_agg(t::text, ' ') FROM (
            SELECT to_jsonb(c)  AS t FROM mia.cliente c UNION ALL
            SELECT to_jsonb(ci) FROM mia.cita ci        UNION ALL
            SELECT to_jsonb(e)  FROM mia.cita_evento e) x""").fetchone()[0]
    for sensible in ["991234567", "Nombre Muy Reconocible", "Ficticia N45"]:
        assert sensible not in volcado


def test_CA8_la_aplicacion_si_puede_recuperar_el_numero_para_responder(bd, claves, manana_10h):
    seud, cif = claves
    registrar(bd, claves, propuesta(manana_10h))
    cifrado = bd("admin").execute("SELECT telefono_cifrado FROM mia.cliente").fetchone()[0]
    assert cif.descifrar(cifrado) == normalizar_telefono(TEL) == "+593991234567"


def test_CA8_el_agente_no_lee_tablas_ni_el_reparto_de_ingresos(bd, claves, manana_10h):
    agente = bd("agente")
    for consulta in ["SELECT * FROM mia.cliente", "SELECT * FROM mia.reparto_participacion",
                     "SELECT * FROM mia.fn_reparto_vigente(current_date)"]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            agente.execute(consulta)


# ─────────────────────────────── CA9 ───────────────────────────────
def test_CA9_cada_cambio_deja_evento_con_actor_y_evidencia(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h))
    bd("aprobacion").execute("SELECT mia.fn_reproponer(%s, 1, '{\"costo_traslado\": \"0\"}'::jsonb, 'le dejo así')", (r.cita_id,))
    bd("aprobacion").execute("SELECT mia.fn_cambiar_estado(%s, 2, 'aprobada', 'listo')", (r.cita_id,))
    bd("sistema").execute("SELECT mia.fn_cambiar_estado(%s, 2, 'confirmada')", (r.cita_id,))
    eventos = bd("lectura").execute("""
        SELECT estado_anterior, estado_nuevo, version, actor, evidencia, rol_bd
          FROM mia.cita_evento WHERE cita_id = %s ORDER BY evento_id""", (r.cita_id,)).fetchall()
    assert eventos == [
        (None, "pendiente_aprobacion", 1, "agente", None, "t_agente"),
        ("pendiente_aprobacion", "pendiente_aprobacion", 2, "propietaria", "le dejo así", "t_aprobacion"),
        ("pendiente_aprobacion", "aprobada", 2, "propietaria", "listo", "t_aprobacion"),
        ("aprobada", "confirmada", 2, "sistema", None, "t_sistema"),
    ]
    m = bd("lectura").execute(
        "SELECT primera_decision, modificaciones_propietaria FROM mia.v_metricas_aprobacion WHERE cita_id = %s",
        (r.cita_id,)).fetchone()
    assert m == ("aprobada", 1)


def test_CA9_el_historial_no_se_edita_ni_se_borra(bd, claves, manana_10h):
    registrar(bd, claves, propuesta(manana_10h))
    admin = bd("admin")
    for sentencia in ["UPDATE mia.cita_evento SET evidencia = 'x'", "DELETE FROM mia.cita_evento",
                      "TRUNCATE mia.cita_evento CASCADE", "DELETE FROM mia.cita"]:
        with pytest.raises(psycopg.errors.RestrictViolation):
            admin.execute(sentencia)


# ─────────────────────────────── CA10 ──────────────────────────────
def test_CA10_reparto_vigente_segun_fecha(bd):
    lectura = bd("lectura")
    antes = lectura.execute("SELECT beneficiario, porcentaje FROM mia.fn_reparto_vigente('2025-06-15')").fetchall()
    ahora = lectura.execute("SELECT beneficiario, porcentaje FROM mia.fn_reparto_vigente('2026-09-20')").fetchall()
    assert [p for _, p in antes] == [D("80.00"), D("20.00")]
    assert [p for _, p in ahora] == [D("70.00"), D("20.00"), D("10.00")]


def test_CA10_un_reparto_debe_sumar_100(bd):
    admin = bd("admin")
    with pytest.raises(psycopg.errors.CheckViolation, match="debe sumar 100"):
        with admin.transaction():
            rid = admin.execute("INSERT INTO mia.reparto_version (vigente_desde) VALUES ('2027-01-01') RETURNING reparto_id").fetchone()[0]
            admin.execute("INSERT INTO mia.reparto_participacion VALUES (%s, 'A', 50), (%s, 'B', 40)", (rid, rid))


def test_CA10_un_reparto_vigente_no_se_edita(bd):
    with pytest.raises(psycopg.errors.RestrictViolation, match="versión nueva"):
        bd("admin").execute("UPDATE mia.reparto_participacion SET porcentaje = porcentaje WHERE beneficiario = 'Mami'")


# ─────────────────────────────── CA11 ──────────────────────────────
def test_CA11_el_descuento_no_supera_el_subtotal(bd, claves, manana_10h):
    with pytest.raises(psycopg.errors.CheckViolation, match="supera el subtotal"):
        registrar(bd, claves, propuesta(manana_10h, descuento=Descuento("primera_vez", "prueba", D("50.00"))))


def test_CA11_beneficio_en_especie_con_monto_cero(bd, claves, manana_10h):
    r = registrar(bd, claves, propuesta(manana_10h, descuento=Descuento(
        "primera_vez", "le regalo baño antipulgas por ser su primera vez")))
    assert obtener_resumen(bd("lectura"), r.cita_id)["total_estimado"] == D("15.00")


def test_CA11_servicio_inexistente_se_rechaza(bd, claves, manana_10h):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        registrar(bd, claves, propuesta(manana_10h, lineas=(Linea(Mascota("Tita"), "XX", cot("10")),)))


def test_CA11_validaciones_previas_en_python(manana_10h, claves):
    seud, cif = claves
    casos = [
        propuesta(manana_10h, telefono_solicitante="12345"),
        propuesta(manana_10h, puerta_a_puerta=True),                      # sin dirección
        propuesta(manana_10h, costo_traslado=D("2.00")),                  # traslado sin domicilio
        replace(propuesta(manana_10h), inicio=manana_10h.replace(tzinfo=None)),  # sin zona horaria
        propuesta(manana_10h, lineas=()),
    ]
    for p in casos:
        with pytest.raises(PropuestaInvalida):
            registrar_cita_propuesta(None, p, seud, cif)


def test_CA11_montos_en_float_se_rechazan():
    with pytest.raises(PropuestaInvalida, match="float"):
        Cotizacion.desde_motor({"precio_estimado": 12.5, "es_comprometido": True})


def test_CA5_dos_reintentos_simultaneos_no_duplican(bd, claves, manana_10h):
    """Dos entregas del mismo webhook procesadas en paralelo."""
    import threading
    seud, cif = claves
    p = propuesta(manana_10h, clave="wamid.CONCURRENTE")
    c1, c2 = bd("agente"), bd("agente")
    resultados, errores = [], []
    barrera = threading.Barrier(2)

    def trabajar(conn):
        try:
            barrera.wait()
            resultados.append(registrar_cita_propuesta(conn, p, seud, cif))
        except Exception as exc:  # noqa: BLE001
            errores.append(exc)

    hilos = [threading.Thread(target=trabajar, args=(c,)) for c in (c1, c2)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert not errores, errores
    assert len({r.cita_id for r in resultados}) == 1
    assert sorted(r.creada for r in resultados) == [False, True]
    assert bd("admin").execute("SELECT count(*) FROM mia.cita").fetchone()[0] == 1
