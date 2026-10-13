"""SCRUM-95/96: línea base desde el export de WhatsApp (chat sintético, sin datos reales)."""

from evaluacion.linea_base.linea_base_whatsapp import analizar, leer_export

CHAT_ANDROID = """\
10/3/25, 9:00 - Cliente Uno: Buenos días, quisiera agendar un baño para mi perrita
10/3/25, 9:01 - Cliente Uno: es una shih tzu
10/3/25, 9:40 - Lina Pet: Hola! sí claro, ¿para qué día?
10/3/25, 9:45 - Cliente Uno: mañana a las 10 puede?
10/3/25, 10:30 - Lina Pet: Listo, le agendo mañana a las 10. Serían 15$
11/3/25, 11:30 - Lina Pet: Con el desenredo quedó en 20$
"""

CHAT_IOS = """\
[12/03/25, 18:00:00] Cliente Dos: cuanto cuesta el baño completo?
[12/03/25, 6:30:00 p. m.] Lina Pet: Hola, depende del tamaño
de su perrito, me manda una foto?
"""


def _escribir(tmp_path, nombre, texto):
    ruta = tmp_path / nombre
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def test_lee_android_e_ios_con_hora_y_lineas_de_continuacion(tmp_path):
    android = leer_export(_escribir(tmp_path, "a.txt", CHAT_ANDROID), "Lina")
    assert len(android) == 6 and android[2].de_propietaria and not android[0].de_propietaria
    ios = leer_export(_escribir(tmp_path, "b.txt", CHAT_IOS), "Lina")
    assert ios[1].momento.hour == 18 and ios[1].momento.minute == 30   # 6:30 p. m.
    assert "me manda una foto" in ios[1].texto                       # continuación unida


def test_tiempos_de_respuesta_confirmacion_y_variacion_de_precio(tmp_path):
    rutas = [_escribir(tmp_path, "a.txt", CHAT_ANDROID), _escribir(tmp_path, "b.txt", CHAT_IOS)]
    res, revision = analizar(rutas, "Lina")
    # Primera respuesta: 40 min (9:00 -> 9:40), 45 min (9:45 -> 10:30, nuevo turno tras su mensaje) y 30 min (chat 2)
    assert res["primera_respuesta"]["n"] == 3
    assert res["primera_respuesta"]["mediana_min"] == 40.0
    # Pedido de cita 9:00 -> "Listo, le agendo" 10:30 = 90 min
    assert res["tiempo_hasta_confirmar"] == {"n": 1, "mediana_min": 90.0, "media_min": 90.0,
                                             "p75_min": 90.0, "p90_min": 90.0}
    # Dijo 15$ y luego 20$ en menos de 7 días
    assert res["variacion_precio_usd"]["n"] == 1 and res["variacion_precio_usd"]["mediana"] == 5.0
    # La salida agregada no lleva textos; la revisión (fuera del repo) sí.
    assert "shih tzu" not in str(res) and any(r["tipo"] == "confirmacion" for r in revision)


def test_chat_sin_la_propietaria_se_ignora(tmp_path):
    res, _ = analizar([_escribir(tmp_path, "c.txt", CHAT_ANDROID)], "OtraPersona")
    assert res["chats_con_propietaria"] == 0 and res["primera_respuesta"]["n"] == 0
