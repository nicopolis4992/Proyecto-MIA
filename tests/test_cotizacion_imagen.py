"""
Pruebas de SCRUM-103 (clasificacion -> tarifario v2) y SCRUM-104 (fallback
por calidad o baja confianza), con un clasificador falso.
"""

import io

import numpy as np
from PIL import Image, ImageFilter

from app.cotizacion.cotizador import Cotizador
from app.cotizacion.cotizador_imagen import cargar_politica, procesar_foto
from app.vision.calidad import evaluar_calidad
from app.vision.clasificador import Clasificacion

COT = Cotizador()
POLITICA = cargar_politica()


def _foto(borrosa=False, brillo=1.0, lado=640) -> bytes:
    rng = np.random.default_rng(0)
    a = (rng.random((lado, lado, 3)) * 255 * brillo).clip(0, 255).astype("uint8")
    img = Image.fromarray(a)
    if borrosa:
        img = img.filter(ImageFilter.GaussianBlur(12))
    b = io.BytesIO()
    img.save(b, "JPEG")
    return b.getvalue()


class ClasificadorFalso:
    def __init__(self, tamano="grande", ct=0.95, grupo="C_cepillado", cg=0.95,
                 estado="sin_motas", ce=0.95, es_perro=True):
        self.r = Clasificacion(es_perro, tamano, ct, grupo, cg, "cnn_onnx", "test", estado, ce)
        self.llamadas = 0

    def clasificar(self, datos):
        self.llamadas += 1
        return self.r


def test_calidad_detecta_borrosa_oscura_y_pequena():
    u = POLITICA["calidad"]
    assert evaluar_calidad(_foto(), u).aceptable
    assert evaluar_calidad(_foto(borrosa=True), u).motivo == "borrosa"
    assert evaluar_calidad(_foto(brillo=0.05), u).motivo == "oscura"
    assert evaluar_calidad(_foto(lado=100), u).motivo == "pequena"
    assert evaluar_calidad(b"no es imagen", u).motivo == "ilegible"


def test_foto_confiable_cotiza_con_los_atributos_del_clasificador():
    # Golden en buen estado, peluqueria completa: el caso real de USD 25.
    r = procesar_foto(_foto(), ClasificadorFalso(), COT, 1, ["completo"],
                      {"comportamiento": "tranquilo"}, politica=POLITICA)
    assert r.accion == "cotizar" and not r.revision_manual
    assert r.atributos == {"tamano": "grande", "grupo": "C_cepillado", "estado": "sin_motas"}
    assert r.cotizaciones["completo"]["total"] == [25, 25]
    # Trazabilidad: backend, version, confianza, umbral y tarifario.
    assert r.traza["clasificacion"]["backend"] == "cnn_onnx"
    assert r.traza["umbrales"] == POLITICA["umbrales_confianza"]["cnn_onnx"]
    assert r.traza["version_tarifario"] == COT.datos["version"]


def test_lo_declarado_por_la_clienta_tiene_prioridad_sobre_la_foto():
    r = procesar_foto(_foto(), ClasificadorFalso(estado="severo"), COT, 1, ["completo"],
                      {"estado": "sin_motas", "comportamiento": "tranquilo"}, politica=POLITICA)
    assert r.cotizaciones["completo"]["total"] == [25, 25]


def test_foto_borrosa_pide_otra_sin_clasificar():
    clf = ClasificadorFalso()
    r = procesar_foto(_foto(borrosa=True), clf, COT, 1, ["completo"], politica=POLITICA)
    assert r.accion == "pedir_otra_foto" and "borrosa" in r.mensaje
    assert clf.llamadas == 0


def test_dimension_bajo_umbral_se_descarta_y_se_pregunta():
    r = procesar_foto(_foto(), ClasificadorFalso(ct=0.40), COT, 1, ["completo"], politica=POLITICA)
    assert r.accion == "cotizar" and "tamano" not in r.atributos
    assert "tamano" in r.cotizaciones["completo"]["preguntas_pendientes"]


def test_tamano_y_grupo_dudosos_piden_otra_foto_y_luego_revision_manual():
    clf = ClasificadorFalso(ct=0.3, cg=0.3)
    assert procesar_foto(_foto(), clf, COT, 1, ["completo"], politica=POLITICA).accion == "pedir_otra_foto"
    r2 = procesar_foto(_foto(), clf, COT, POLITICA["max_fotos_por_mascota"], ["completo"], politica=POLITICA)
    assert r2.accion == "cotizar" and r2.revision_manual
    total = r2.cotizaciones["completo"]["total"]
    assert total[0] < total[1]


def test_no_es_perro_pide_otra_foto():
    r = procesar_foto(_foto(), ClasificadorFalso(es_perro=False), COT, 1, ["completo"], politica=POLITICA)
    assert r.accion == "pedir_otra_foto"


def test_deslanado_a_perro_de_maquina_sugiere_completo():
    r = procesar_foto(_foto(), ClasificadorFalso(grupo="A_maquina"), COT, 1, ["deslanado"], politica=POLITICA)
    assert r.cotizaciones["deslanado"]["mascotas"][0]["no_aplica"]
    assert "Baño Completo" in r.mensaje


def test_varios_servicios_cuando_la_clienta_no_eligio():
    r = procesar_foto(_foto(), ClasificadorFalso(), COT, 1, ["basico", "completo"], politica=POLITICA)
    assert set(r.cotizaciones) == {"basico", "completo"}
    assert "Baño Básico" in r.mensaje and "Baño Completo" in r.mensaje
