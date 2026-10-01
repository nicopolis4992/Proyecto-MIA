"""
SCRUM-101 — Pruebas automatizadas, nombradas por criterio de aceptación.

Se sigue la misma convención de SCRUM-98: cada prueba declara en su nombre el
criterio que verifica, de modo que la evidencia de cumplimiento sea legible sin
leer el código.

    python -m pytest tests/ -v          (o)     python tests/test_scrum101.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ))

os.environ.setdefault("MIA_SAL_SEUDONIMO", "sal-de-prueba-no-usar-en-produccion")

from anonimizacion import (  # noqa: E402
    SalNoConfigurada,
    agrupar_duplicados,
    distancia_hamming,
    hash_perceptual,
    limpiar_metadatos,
    seudonimo,
)
from clases import (  # noqa: E402
    CLASES_PELAJE,
    CLASES_TAMANO,
    CLAVES_PELAJE,
    CLAVES_TAMANO,
    clasificar_peso,
    clasificar_rango_peso,
    verificar_contra_tarifario,
)
from dataset import (  # noqa: E402
    FUENTE_CAPTURA,
    FUENTE_INSTAGRAM,
    FUENTE_STANFORD,
    Registro,
    particionar,
    verificar_particion,
)
from degradacion import degradar, reescalar_canal  # noqa: E402
from mapeo_razas import (  # noqa: E402
    NO_DOMESTICAS,
    RAZAS,
    construir_mapeo,
    integridad_tabla,
    validar_cobertura,
)
from reporte import brecha, cobertura, n_minimo_por_clase, semiamplitud_para  # noqa: E402


# ===========================================================================
# CA1 — El dataset consolida Stanford Dogs con las fotografías propias
# ===========================================================================

def test_CA1_la_tabla_cubre_las_120_razas_de_stanford_dogs():
    assert len(RAZAS) == 120
    assert integridad_tabla() == []


def test_CA1_toda_raza_recibe_una_decision_de_uso_explicita():
    usos = {f["uso"] for f in construir_mapeo()}
    assert usos <= {"completa", "solo_pelaje", "excluida"}
    assert all(f["uso"] for f in construir_mapeo())


def test_CA1_una_raza_presente_en_disco_y_ausente_de_la_tabla_se_detecta():
    resultado = validar_cobertura(["chihuahua", "raza_inventada"])
    assert "raza_inventada" in resultado["sin_mapeo"]


def test_CA1_los_canidos_no_domesticos_quedan_excluidos():
    mapa = {f["slug"]: f for f in construir_mapeo()}
    for slug in NO_DOMESTICAS:
        assert mapa[slug]["uso"] == "excluida"


# ===========================================================================
# CA2 — Toda fotografía queda anonimizada antes de su uso
# ===========================================================================

def _imagen_con_exif(ruta: Path) -> Path:
    img = Image.new("RGB", (240, 180), (120, 90, 60))
    exif = img.getexif()
    exif[0x010F] = "ACME"          # Make
    exif[0x0110] = "Modelo-X"      # Model
    exif[0x0132] = "2026:09:20 10:00:00"
    img.save(ruta, format="JPEG", exif=exif.tobytes())
    return ruta


def test_CA2_la_limpieza_elimina_todos_los_metadatos():
    with tempfile.TemporaryDirectory() as tmp:
        origen = _imagen_con_exif(Path(tmp) / "origen.jpg")
        destino = Path(tmp) / "limpia.jpg"
        resultado = limpiar_metadatos(origen, destino)

        assert set(resultado.campos_hallados) >= {"Make", "Model"}
        with Image.open(destino) as salida:
            assert not dict(salida.getexif())


def test_CA2_el_seudonimo_es_determinista_y_no_revela_el_identificador():
    sal = b"sal-fija"
    a = seudonimo("0999123456", sal)
    b = seudonimo(" 0999123456 ", sal)
    assert a == b, "el seudónimo debe normalizar espacios y mayúsculas"
    assert "0999123456" not in a
    assert len(a) == 16


def test_CA2_seudonimos_distintos_con_sales_distintas():
    assert seudonimo("0999123456", b"sal-A") != seudonimo("0999123456", b"sal-B")


def test_CA2_sin_sal_configurada_el_pipeline_se_detiene():
    original = os.environ.pop("MIA_SAL_SEUDONIMO", None)
    try:
        import anonimizacion as anon
        try:
            anon.obtener_sal()
            assert False, "debía lanzar SalNoConfigurada"
        except SalNoConfigurada:
            pass
    finally:
        if original is not None:
            os.environ["MIA_SAL_SEUDONIMO"] = original


def test_CA2_los_casi_duplicados_se_agrupan():
    import numpy as np
    from PIL import ImageFilter

    with tempfile.TemporaryDirectory() as tmp:
        # Imagen con estructura de fotografía (gradientes suaves), no ruido:
        # el pHash está diseñado para contenido natural, no para patrones de
        # alta frecuencia.
        yy, xx = np.mgrid[0:240, 0:320]
        arr = np.zeros((240, 320, 3), dtype=np.uint8)
        arr[..., 0] = (128 + 100 * np.sin(xx / 40.0)).astype(np.uint8)
        arr[..., 1] = (128 + 100 * np.cos(yy / 35.0)).astype(np.uint8)
        arr[..., 2] = ((xx + yy) % 256).astype(np.uint8)
        base = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(1.5))

        p1 = Path(tmp) / "a.jpg"
        p2 = Path(tmp) / "b.jpg"
        base.save(p1, quality=95)
        base.resize((300, 225)).save(p2, quality=60)  # misma foto, recomprimida

        hashes = {"a": hash_perceptual(p1), "b": hash_perceptual(p2)}
        assert distancia_hamming(hashes["a"], hashes["b"]) <= 5
        assert agrupar_duplicados(hashes) == [["a", "b"]]


# ===========================================================================
# CA3 — Las etiquetas corresponden a las clases del tarifario de SCRUM-98
# ===========================================================================

def test_CA3_los_cortes_de_peso_replican_el_tarifario():
    assert clasificar_peso(9.0) == "pequeno"
    assert clasificar_peso(9.1) == "mediano"
    assert clasificar_peso(18.0) == "mediano"
    assert clasificar_peso(18.1) == "grande"
    assert clasificar_peso(45.0) == "grande"
    assert clasificar_peso(45.1) == "fuera_de_rango"


def test_CA3_una_raza_que_cruza_un_corte_se_marca_ambigua():
    # Beagle: 9,0–11,3 kg, atraviesa el corte de 9,0/9,1
    _, ambigua = clasificar_rango_peso(9.0, 11.3)
    assert ambigua is True
    # Pug: 6,3–8,1 kg, íntegramente pequeño
    _, ambigua_pug = clasificar_rango_peso(6.3, 8.1)
    assert ambigua_pug is False


def test_CA3_las_razas_ambiguas_no_aportan_etiqueta_de_tamano():
    mapa = {f["slug"]: f for f in construir_mapeo()}
    assert mapa["beagle"]["uso"] == "solo_pelaje"
    assert mapa["pug"]["uso"] == "completa"


def test_CA3_todo_pelaje_pertenece_a_la_taxonomia_del_tarifario():
    assert all(f["pelaje"] in CLAVES_PELAJE for f in construir_mapeo())


def _tarifario_temporal(tmp: str, pelajes: list[dict]) -> Path:
    # Misma estructura que tarifario_v1.json de SCRUM-98.
    ruta = Path(tmp) / "tarifario.json"
    ruta.write_text(json.dumps({
        "clasificacion_tamano": [
            {"codigo": c.clave, "peso_kg_min": c.peso_min_kg, "peso_kg_max": c.peso_max_kg}
            for c in CLASES_TAMANO
        ],
        "clasificacion_pelaje": pelajes,
    }), encoding="utf-8")
    return ruta


def test_CA3_el_verificador_lee_la_estructura_real_del_tarifario():
    pelajes = [{"codigo": c.clave, "factor": c.factor} for c in CLASES_PELAJE]
    with tempfile.TemporaryDirectory() as tmp:
        assert verificar_contra_tarifario(_tarifario_temporal(tmp, pelajes)) == []


def test_CA3_el_verificador_detecta_clases_y_factores_divergentes():
    pelajes = [{"codigo": c.clave, "factor": c.factor} for c in CLASES_PELAJE]
    pelajes[1] = {"codigo": "doble_capa", "factor": 1.25}
    pelajes[2] = {"codigo": pelajes[2]["codigo"], "factor": 9.99}
    with tempfile.TemporaryDirectory() as tmp:
        problemas = verificar_contra_tarifario(_tarifario_temporal(tmp, pelajes))
    assert any("Clases de pelaje divergentes" in p for p in problemas)
    assert any("Factor de pelaje divergente" in p for p in problemas)


def test_CA3_el_pelo_duro_queda_marcado_como_no_cubierto():
    mapa = {f["slug"]: f for f in construir_mapeo()}
    assert mapa["miniature_schnauzer"]["pelaje_observacion"] == "duro"


# ===========================================================================
# CA4 — La partición es reproducible y sin fuga
# ===========================================================================

def _registros_de_prueba(n_mascotas: int = 12, fotos: int = 3) -> list[Registro]:
    regs: list[Registro] = []
    pelajes = list(CLAVES_PELAJE)
    tamanos = list(CLAVES_TAMANO)
    for m in range(n_mascotas):
        for k in range(fotos):
            regs.append(
                Registro(
                    id_imagen=f"r_{m}_{k}",
                    fuente=FUENTE_INSTAGRAM if k == 0 else FUENTE_CAPTURA,
                    ruta=f"x/{m}_{k}.jpg",
                    mascota_id=f"mascota_{m}",
                    tamano=tamanos[m % len(tamanos)],
                    pelaje=pelajes[m % len(pelajes)],
                    revision_manual=1,
                )
            )
    for i in range(30):
        regs.append(
            Registro(
                id_imagen=f"sd_{i}",
                fuente=FUENTE_STANFORD,
                ruta=f"sd/{i}.jpg",
                mascota_id=f"sd_{i}",
                tamano=tamanos[i % len(tamanos)],
                pelaje=pelajes[i % len(pelajes)],
            )
        )
    return regs


def test_CA4_la_particion_es_reproducible_con_la_misma_semilla():
    a = _registros_de_prueba()
    b = _registros_de_prueba()
    particionar(a, semilla=42)
    particionar(b, semilla=42)
    assert [r.particion for r in a] == [r.particion for r in b]


def test_CA4_ninguna_mascota_aparece_en_dos_particiones():
    regs = _registros_de_prueba()
    particionar(regs)
    por_mascota: dict[str, set[str]] = {}
    for r in regs:
        if r.fuente != FUENTE_STANFORD:
            por_mascota.setdefault(r.mascota_id, set()).add(r.particion)
    assert all(len(p) == 1 for p in por_mascota.values())


def test_CA4_la_verificacion_detecta_una_fuga_inyectada():
    regs = _registros_de_prueba()
    particionar(regs)
    objetivo = next(r for r in regs if r.fuente != FUENTE_STANFORD)
    objetivo.particion = "train" if objetivo.particion == "test" else "test"
    problemas = verificar_particion(regs)
    assert any("FUGA" in p for p in problemas)


def test_CA4_una_foto_sin_revision_manual_bloquea_el_cierre():
    regs = _registros_de_prueba()
    regs[0].revision_manual = 0
    particionar(regs)
    assert any("PROTOCOLO" in p for p in verificar_particion(regs))


# ===========================================================================
# CA5 — El conjunto de prueba refleja el dominio de despliegue
# ===========================================================================

def test_CA5_stanford_dogs_nunca_llega_al_conjunto_de_prueba():
    regs = _registros_de_prueba()
    particionar(regs)
    assert all(r.particion == "train" for r in regs if r.fuente == FUENTE_STANFORD)


def test_CA5_la_verificacion_detecta_contaminacion_del_test():
    regs = _registros_de_prueba()
    particionar(regs)
    next(r for r in regs if r.fuente == FUENTE_STANFORD).particion = "test"
    assert any("CONTAMINACIÓN" in p for p in verificar_particion(regs))


def test_CA5_el_test_se_nutre_solo_de_fotografias_propias():
    regs = _registros_de_prueba()
    particionar(regs)
    en_test = [r for r in regs if r.particion == "test"]
    assert en_test, "el conjunto de prueba no puede quedar vacío"
    assert all(r.fuente in {FUENTE_INSTAGRAM, FUENTE_CAPTURA} for r in en_test)


def test_CA5_la_degradacion_simula_el_reescalado_del_canal():
    grande = Image.new("RGB", (4000, 3000), (10, 20, 30))
    reducida = reescalar_canal(grande)
    assert max(reducida.size) == 1600


def test_CA5_la_degradacion_produce_una_imagen_valida():
    img = Image.new("RGB", (800, 600), (200, 180, 160))
    salida = degradar(img)
    assert salida.size[0] > 0 and salida.size[1] > 0
    assert salida.mode == "RGB"


# ===========================================================================
# CA6 — El dataset documenta su propia cobertura y sus faltantes
# ===========================================================================

def test_CA6_el_minimo_por_clase_se_calcula_y_no_se_fija_a_dedo():
    assert n_minimo_por_clase(0.85, 0.10) == 49
    assert n_minimo_por_clase(0.85, 0.05) == 196
    assert n_minimo_por_clase(0.85, 0.20) == 13


def test_CA6_un_test_mas_pequeno_produce_un_intervalo_mas_ancho():
    assert semiamplitud_para(20) > semiamplitud_para(100)


def test_CA6_el_reporte_cuenta_mascotas_no_solo_imagenes():
    regs = _registros_de_prueba(n_mascotas=7, fotos=4)
    particionar(regs)
    cob = cobertura(regs)
    assert cob["mascotas_distintas"] == 7
    assert cob["total_dominio_real"] == 28


def test_CA6_la_brecha_expresa_el_faltante_en_fotografias_a_capturar():
    regs = _registros_de_prueba()
    particionar(regs)
    b = brecha(regs)
    assert b["n_minimo_por_clase_en_test"] == 49
    assert b["captura_total_necesaria"] > 0
    for filas in b["detalle"].values():
        for f in filas.values():
            assert f["fotos_reales_a_capturar"] >= f["falta_en_test"]


def test_CA6_la_cobertura_reporta_la_escasez_de_la_clase_mediana():
    mapa = construir_mapeo()
    completas = [f for f in mapa if f["uso"] == "completa"]
    conteo = {c: sum(1 for f in completas if f["tamano"] == c) for c in CLAVES_TAMANO}
    # Hallazgo documentado en el anexo: la clase mediana es la peor cubierta.
    assert conteo["mediano"] == min(conteo.values())
    assert conteo["mediano"] <= 10


# ===========================================================================

if __name__ == "__main__":
    fallos = 0
    pruebas = [(n, o) for n, o in sorted(globals().items())
               if n.startswith("test_") and callable(o)]
    for nombre, prueba in pruebas:
        try:
            prueba()
            print(f"  OK   {nombre}")
        except Exception as e:  # noqa: BLE001
            fallos += 1
            print(f"  FALLA {nombre}: {type(e).__name__}: {e}")
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas superadas.")
    raise SystemExit(1 if fallos else 0)
