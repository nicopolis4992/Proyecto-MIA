"""
Pruebas de SCRUM-103 (clasificacion -> motor de cotizacion) y SCRUM-104
(fallback por calidad o baja confianza), con un clasificador falso.
"""

import io

import numpy as np
from PIL import Image, ImageFilter

from app.config import RUTA_TARIFARIO
from app.cotizacion.cotizador_imagen import cargar_politica, procesar_foto
from app.cotizacion.motor_cotizacion import Motor
from app.vision.calidad import evaluar_calidad
from app.vision.clasificador import Clasificacion

MOTOR = Motor(RUTA_TARIFARIO)
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
    def __init__(self, tamano="grande", ct=0.95, pelaje="doble_capa", cp=0.95, es_perro=True):
        self.r = Clasificacion(es_perro, tamano, ct, pelaje, cp, "cnn_onnx", "test")
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


def test_foto_confiable_cotiza_con_tamano_y_pelaje():
    r = procesar_foto(_foto(), ClasificadorFalso(), MOTOR, 1, ["bano"], politica=POLITICA)
    assert r.accion == "cotizar" and not r.revision_manual
    c = r.cotizaciones["bano"]
    assert c["detalle_por_mascota"][0]["tamano_aplicado"] == "grande"
    assert c["detalle_por_mascota"][0]["pelaje_aplicado"] == "doble_capa"
    assert "tamano" not in c["datos_faltantes"]
    # Trazabilidad: backend, version, confianza y umbral quedan registrados.
    assert r.traza["clasificacion"]["backend"] == "cnn_onnx"
    assert r.traza["umbrales"] == POLITICA["umbrales_confianza"]["cnn_onnx"]


def test_foto_borrosa_pide_otra_sin_clasificar():
    clf = ClasificadorFalso()
    r = procesar_foto(_foto(borrosa=True), clf, MOTOR, 1, ["bano"], politica=POLITICA)
    assert r.accion == "pedir_otra_foto" and "borrosa" in r.mensaje
    assert clf.llamadas == 0


def test_dimension_bajo_umbral_se_descarta_y_ensancha_la_banda():
    r = procesar_foto(_foto(), ClasificadorFalso(ct=0.40), MOTOR, 1, ["bano"], politica=POLITICA)
    assert r.accion == "cotizar" and r.tamano is None and r.pelaje == "doble_capa"
    assert "tamano" in r.cotizaciones["bano"]["datos_faltantes"]


def test_ambas_bajo_umbral_pide_otra_foto_y_luego_revision_manual():
    clf = ClasificadorFalso(ct=0.3, cp=0.3)
    r1 = procesar_foto(_foto(), clf, MOTOR, 1, ["bano"], politica=POLITICA)
    assert r1.accion == "pedir_otra_foto"
    r2 = procesar_foto(_foto(), clf, MOTOR, POLITICA["max_fotos_por_mascota"], ["bano"], politica=POLITICA)
    assert r2.accion == "cotizar" and r2.revision_manual
    assert r2.cotizaciones["bano"]["tipo_cotizacion"] == "rango_estimado"


def test_no_es_perro_pide_otra_foto():
    r = procesar_foto(_foto(), ClasificadorFalso(es_perro=False), MOTOR, 1, ["bano"], politica=POLITICA)
    assert r.accion == "pedir_otra_foto"


def test_deslanado_en_pelaje_corto_cotiza_bano_y_lo_explica():
    r = procesar_foto(_foto(), ClasificadorFalso(pelaje="corto"), MOTOR, 1, ["deslanado"], politica=POLITICA)
    assert list(r.cotizaciones) == ["bano"]
    assert "solo aplica" in r.mensaje


def test_varios_servicios_cuando_el_cliente_no_eligio():
    r = procesar_foto(_foto(), ClasificadorFalso(), MOTOR, 1, ["bano", "bano_corte"], politica=POLITICA)
    assert set(r.cotizaciones) == {"bano", "bano_corte"}
    assert "Baño e higiene básica" in r.mensaje and "Baño y corte" in r.mensaje
