"""SCRUM-71: métricas de la evaluación del RAG, con recuperación y respuestas simuladas (sin Gemini)."""

from evaluacion.rag.evaluar_rag import contiene_dato, evaluar

FILAS = [
    {"pregunta": "horario sabado", "datos": ["08:00", "18:00"], "debe_declinar": False, "categoria": "horarios"},
    {"pregunta": "como se paga", "datos": ["transferencia"], "debe_declinar": False, "categoria": "politicas|faq"},
    {"pregunta": "aceptan tarjeta", "datos": [], "debe_declinar": True, "categoria": ""},
    {"pregunta": "donde queda", "datos": [], "debe_declinar": True, "categoria": ""},
]
RECUPERA = {"horario sabado": [("horarios", 0.80)], "como se paga": [("faq", 0.72), ("politicas", 0.70)],
            "aceptan tarjeta": [("politicas", 0.68)], "donde queda": [("negocio", 0.55)]}
RESPONDE = {"horario sabado": ("Los sábados de 08:00 a 18:00", True),
            "como se paga": ("En efectivo", True),                     # dato equivocado
            "aceptan tarjeta": ("Sí, aceptamos tarjeta", True),        # alucinación
            "donde queda": ("No tengo esa información", False)}


def test_metricas_de_recuperacion_respuesta_y_umbral():
    r = evaluar(FILAS, RECUPERA.get, RESPONDE.get, umbral_actual=0.66)
    assert r["recuperacion"]["hit1_pct"] == 100.0                     # "faq" vale para "politicas|faq"
    assert r["respuestas"] == {"exactitud_pct": 50.0, "respondio_lo_que_sabe_pct": 100.0,
                               "no_se_correcto_pct": 50.0, "alucinacion_pct": 50.0}
    # Con 0,66 "aceptan tarjeta" (0,68) pasaria como "sabe"; el umbral propuesto lo separa.
    assert r["umbral_actual"]["declina_lo_que_no_sabe_pct"] == 50.0
    assert r["umbral_propuesto"]["exactitud_balanceada_pct"] == 100.0
    assert 0.68 < r["umbral_propuesto"]["umbral"] <= 0.72


def test_solo_recuperacion_no_llama_a_responder():
    r = evaluar(FILAS, RECUPERA.get)
    assert "respuestas" not in r and r["n_sabe"] == 2 and r["n_no_sabe"] == 2


def test_contiene_dato_tolera_formatos_de_numero():
    assert contiene_dato("Cuesta USD 20.00", "20")
    assert contiene_dato("de 7,50$ a 9$", "7.5")
    assert not contiene_dato("Cuesta 120", "20")
    assert contiene_dato("Por transferencia bancaria", "Transferencia")
