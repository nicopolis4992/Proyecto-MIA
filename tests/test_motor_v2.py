"""
Pruebas del motor v2. Las de la clase CasosReales reproducen los precios que la
propietaria dio en sus audios del 04/10/2026; si alguna falla, el tarifario dejó de
representar al negocio.
"""
from datetime import datetime
from pathlib import Path

import pytest

from app.cotizacion.motor_cotizacion_v2 import Tarifario, cotizar, cotizar_mascota, restringido_pico_y_placa

T = Tarifario.desde_archivo(Path(__file__).resolve().parents[1] / "app" / "cotizacion" / "tarifario_v2.json")


def precio(**m):
    r = cotizar_mascota(T, {"comportamiento": "tranquilo", **m})
    return r


class TestCasosReales:
    """Precios dichos por la propietaria (tolerancia ±1,5 USD salvo indicación)."""

    @pytest.mark.parametrize("caso, mascota, esperado, tol", [
        ("shih tzu buen estado", dict(raza="shih tzu", estado="sin_motas", servicio="completo"), 15, 0),
        ("shih tzu en mal estado", dict(raza="shih tzu", estado="severo", servicio="completo"), 20, 0),
        ("golden peluquería", dict(raza="golden", estado="sin_motas", servicio="completo"), 25, 0),
        ("pastor inglés peluquería", dict(raza="pastor ingles", estado="sin_motas", servicio="completo"), 45, 0),
        ("pastor inglés desenredo", dict(raza="pastor ingles", estado="severo", servicio="completo"), 70, 0),
        ("pastor inglés solo baño", dict(raza="pastor ingles", estado="sin_motas", servicio="express"), 25, 1.5),
        ("rottweiler mestizo medicado", dict(raza="mestizo", tamano="grande", grupo="D_corto",
                                             estado="sin_motas", servicio="premium"), 17, 0),
        ("mestiza mediana sin motas", dict(raza="mestizo", tamano="mediano", grupo="A_maquina",
                                           estado="sin_motas", servicio="completo"), 18, 0),
        ("mestiza mediana con motas", dict(raza="mestizo", tamano="mediano", grupo="A_maquina",
                                           estado="moderado", servicio="completo"), 22, 0),
        ("pug deslanado", dict(raza="pug", estado="sin_motas", servicio="deslanado"), 12, 0),
    ])
    def test_precio_puntual(self, caso, mascota, esperado, tol):
        r = precio(**mascota)
        lo, hi = r["rango"]
        assert lo == hi, f"{caso}: un caso totalmente declarado debe dar un solo precio"
        assert abs(lo - esperado) <= tol, f"{caso}: motor {lo}, propietaria {esperado}"
        assert r["comprometido"]

    def test_husky_deslanado_rango(self):
        r = precio(raza="husky", estado="sin_motas", servicio="deslanado")
        assert r["rango"] == [25, 35]
        assert r["comprometido"] is False  # el rango propio supera el umbral
        assert r["duracion_min"] == [180, 240]

    def test_pug_mas_barato_que_shih_tzu(self):
        """Corrige el orden invertido del factor de pelaje de v1."""
        pug = precio(raza="pug", estado="sin_motas", servicio="deslanado")["rango"][0]
        shih = precio(raza="shih tzu", estado="sin_motas", servicio="completo")["rango"][0]
        assert pug < shih


class TestExclusiones:
    def test_mas_de_45_kg(self):
        r = cotizar_mascota(T, {"peso_kg": 48, "servicio": "express"})
        assert r["rechazada"]

    def test_45_kg_exactos_se_atiende(self):
        r = cotizar_mascota(T, {"peso_kg": 45, "servicio": "express", "raza": "golden",
                                "estado": "sin_motas", "comportamiento": "tranquilo"})
        assert not r["rechazada"]

    def test_agresivo_declarado(self):
        r = cotizar_mascota(T, {"raza": "shih tzu", "comportamiento": "agresivo_declarado",
                                "servicio": "completo"})
        assert r["rechazada"]

    def test_pelo_no_recuperable_pasa_a_la_propietaria(self):
        r = cotizar_mascota(T, {"raza": "shih tzu", "estado": "no_recuperable", "servicio": "completo"})
        assert r["rango"] is None and "decision_propietaria" in r["requiere"]


class TestBanda:
    def test_solo_foto_no_compromete(self):
        r = cotizar_mascota(T, {"servicio": "completo"})
        assert not r["comprometido"]
        assert set(r["preguntas_sugeridas"]) == {"tamano", "raza_o_grupo_manto",
                                                 "estado_manto", "comportamiento"}

    def test_cada_respuesta_estrecha_el_rango(self):
        anchos = []
        m = {"servicio": "completo"}
        for k, v in [("raza", "shih tzu"), ("estado", "sin_motas"), ("comportamiento", "tranquilo")]:
            m[k] = v
            r = cotizar_mascota(T, dict(m))
            anchos.append(r["rango"][1] - r["rango"][0])
        assert anchos == sorted(anchos, reverse=True)
        assert anchos[-1] == 0

    def test_comportamiento_dificil_no_compromete(self):
        r = cotizar_mascota(T, {"raza": "shih tzu", "estado": "sin_motas",
                                "comportamiento": "dificil", "servicio": "completo"})
        assert r["rango"] == [15, 18]
        assert not r["comprometido"]

    def test_preguntas_ordenadas_por_impacto(self):
        r = cotizar_mascota(T, {"servicio": "completo"})
        imp = r["impacto_usd_por_pregunta"]
        orden = r["preguntas_sugeridas"]
        assert [imp[p] for p in orden] == sorted(imp.values(), reverse=True)


class TestVisita:
    base = {"raza": "shih tzu", "estado": "sin_motas", "comportamiento": "tranquilo", "servicio": "completo"}

    def test_traslado_por_sector(self):
        r = cotizar({"mascotas": [self.base], "traslado": {"sector": "Cotocollao"}}, T)
        assert r["total"] == [20, 20] and r["comprometido"]

    def test_traslado_sector_desconocido(self):
        r = cotizar({"mascotas": [self.base], "traslado": {"sector": "Cumbayá"}}, T)
        assert r["total"] is None and not r["comprometido"]

    def test_la_carolina_es_rango(self):
        r = cotizar({"mascotas": [self.base], "traslado": {"sector": "La Carolina"}}, T)
        assert r["total"] == [25, 30] and not r["comprometido"]

    def test_traslado_una_vez_por_visita(self):
        r = cotizar({"mascotas": [self.base, self.base], "traslado": {"zona": "zona_5"}}, T)
        assert r["total"] == [35, 35]

    def test_sin_descuento_con_tres(self):
        r = cotizar({"mascotas": [self.base] * 3}, T)
        assert r["descuento_multi_mascota"] == [0, 0] and r["total"] == [45, 45]

    def test_descuento_desde_cuatro(self):
        r = cotizar({"mascotas": [self.base] * 4}, T)
        assert r["descuento_multi_mascota"] == [4, 8]
        assert r["total"] == [52, 56]

    def test_mascota_rechazada_no_suma(self):
        r = cotizar({"mascotas": [self.base, {"peso_kg": 50, "servicio": "express"}]}, T)
        assert r["total"] == [15, 15]

    def test_iva_pendiente_avisado(self):
        r = cotizar({"mascotas": [self.base]}, T)
        assert any("iva_pendiente" in a for a in r["avisos"])


class TestPicoYPlaca:
    # 08/10/2026 es jueves
    @pytest.mark.parametrize("hora, esperado", [
        ("2026-10-08 06:00", True), ("2026-10-08 09:29", True), ("2026-10-08 09:30", False),
        ("2026-10-08 12:00", False), ("2026-10-08 16:00", True), ("2026-10-08 19:59", True),
        ("2026-10-08 20:00", False), ("2026-10-07 07:00", False), ("2026-10-10 07:00", False),
    ])
    def test_ventanas(self, hora, esperado):
        assert restringido_pico_y_placa(datetime.fromisoformat(hora), T) is esperado

    def test_feriado(self):
        dt = datetime.fromisoformat("2026-10-08 07:00")
        assert restringido_pico_y_placa(dt, T, feriados={dt.date()}) is False


def test_tarifario_sin_precios_en_codigo():
    """Todo número de negocio debe venir del JSON."""
    codigo = (Path(__file__).resolve().parents[1] / "app" / "cotizacion" / "motor_cotizacion_v2.py").read_text(encoding="utf-8")
    for numero in ["1.25", "3.75", "2.08", "0.33", "0.56", " 15 ", " 45 "]:
        assert numero not in codigo


def test_pesos_en_los_bordes_no_quedan_sin_tamano():
    for peso, esperado in [(0.5, "pequeno"), (9.0, "pequeno"), (9.005, "mediano"), (9.01, "mediano"),
                           (18.0, "mediano"), (18.005, "grande"), (45.0, "grande")]:
        r = cotizar_mascota(T, {"peso_kg": peso, "servicio": "basico", "grupo": "D_corto",
                                "estado": "sin_motas", "comportamiento": "tranquilo"})
        assert "tamano" not in r["preguntas_sugeridas"], (peso, r)
        assert r["escenarios_evaluados"] == 1


# --- Correcciones de integracion (04/10/2026) ------------------------------

def test_deslanado_no_se_cotiza_a_razas_sin_doble_capa():
    r = cotizar_mascota(T, {"raza": "shih tzu", "servicio": "deslanado"})
    assert r["no_aplica"] and r["rango"] is None
    assert r["sugerencia_servicio"] == "completo"
    # Con grupo desconocido se asume doble capa (el servicio lo implica).
    assert cotizar_mascota(T, {"servicio": "deslanado", "tamano": "grande", "estado": "sin_motas",
                               "comportamiento": "tranquilo"})["rango"] == [25, 35]


@pytest.mark.parametrize("escrito, clave", [
    ("shitsu", "shih tzu"), ("Shih-Tzu", "shih tzu"), ("SHITZU", "shih tzu"),
    ("golden retriever", "golden"), ("Golden Retriver", "golden"),
    ("chiguagua", "chihuahua"), ("pastor alemán", "pastor aleman"),
    ("chusco", "mestizo"), ("snauzer", "schnauzer"),
])
def test_razas_mal_escritas_se_reconocen(escrito, clave):
    assert T.resolver_raza(escrito)[0] == clave


def test_raza_desconocida_no_se_adivina():
    assert T.resolver_raza("xoloitzcuintle") is None
    r = cotizar_mascota(T, {"raza": "xoloitzcuintle", "servicio": "completo"})
    assert "tamano" in r["preguntas_sugeridas"]
    assert any("no reconocida" in a for a in r["avisos"])


def test_cruce_usa_la_union_de_ambas_razas():
    # shih tzu (A, pequeño) x golden (C, grande): el rango cubre ambas.
    r = cotizar_mascota(T, {"raza": "shih tzu con golden", "servicio": "completo",
                            "estado": "sin_motas", "comportamiento": "tranquilo"})
    assert r["rango"] == [15, 45]  # incluye grande con pelo de máquina (12 x 3.75)
    assert r["escenarios_evaluados"] == 4  # 2 tamaños x 2 grupos


def test_mestizo_de_raza_conocida_usa_la_predominante_con_aviso():
    r = cotizar_mascota(T, {"raza": "mestizo de rottweiler", "servicio": "premium",
                            "estado": "sin_motas", "comportamiento": "tranquilo"})
    assert r["rango"] == [17, 17]  # mismo caso real de la propietaria
    assert any("predominante" in a for a in r["avisos"])


def test_mestizo_sin_mas_datos_pregunta_tamano_primero():
    r = cotizar_mascota(T, {"raza": "mestizo", "servicio": "completo"})
    assert r["preguntas_sugeridas"][0] == "tamano"


@pytest.mark.parametrize("entrada, campo, esperado", [
    ({"estado": "leve"}, "estado", "moderado"),
    ({"estado": "Muchos nudos"}, "estado", "severo"),
    ({"comportamiento": "nervioso"}, "comportamiento", "dificil"),
    ({"tamano": "Pequeño"}, "tamano", "pequeno"),
    ({"servicio": "peluquería"}, "servicio", "completo"),
])
def test_sinonimos_se_traducen(entrada, campo, esperado):
    from app.cotizacion.motor_cotizacion_v2 import normalizar_entrada
    limpio, avisos = normalizar_entrada(T, entrada)
    assert limpio[campo] == esperado and avisos == []


def test_valor_desconocido_no_rompe_el_motor():
    r = cotizar_mascota(T, {"raza": "golden", "servicio": "completo", "estado": "regular",
                            "comportamiento": "tranquilo"})
    assert r["rango"] is not None and "estado_manto" in r["preguntas_sugeridas"]
    assert any("regular" in a for a in r["avisos"])


def test_agresivo_declarado_con_sinonimo_se_rechaza():
    assert cotizar_mascota(T, {"servicio": "basico", "comportamiento": "bravo"})["rechazada"]
