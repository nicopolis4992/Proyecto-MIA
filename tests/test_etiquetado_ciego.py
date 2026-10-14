"""SCRUM-105: etiquetado a ciegas de las fotos de prueba (estandar de oro de la propietaria)."""

import csv

from entrenamiento.clasificador_imagen import revisar


def test_el_csv_ciego_solo_trae_fotos_de_prueba_sin_ninguna_pista(tmp_path):
    manifiesto = tmp_path / "manifiesto.csv"
    with open(manifiesto, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["ruta", "mascota_id", "tamano", "grupo", "estado", "particion"])
        w.writeheader()
        for i in range(10):
            w.writerow({"ruta": f"imagenes/FB_M{i:03d}_antes.jpg", "mascota_id": f"M{i}", "tamano": "pequeno",
                        "grupo": "A_maquina", "estado": "sin_motas", "particion": "test" if i < 4 else "train"})
    salida = tmp_path / "oro.csv"
    assert revisar.preparar_ciego(manifiesto, salida) == 4
    filas = list(csv.DictReader(open(salida, encoding="utf-8-sig")))
    assert len(filas) == 4
    for f in filas:
        assert f["tamano"] == f["grupo"] == f["estado"] == "" and f["revisado"] == ""
        assert not f["momento"] and not f["id_mascota_prov"]                 # ni mascota ni antes/despues
        assert f["id_imagen"].startswith("foto_") and "antes" not in f["id_imagen"]
    # No pisa lo que ya etiqueto la propietaria
    with open(salida, "a", encoding="utf-8-sig") as fh:
        fh.write("")
    filas[0]["tamano"] = "grande"
    with open(salida, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=revisar.COLUMNAS_CIEGO)
        w.writeheader()
        w.writerows(filas)
    assert revisar.preparar_ciego(manifiesto, salida) == 4
    assert list(csv.DictReader(open(salida, encoding="utf-8-sig")))[0]["tamano"] == "grande"


def test_las_listas_no_preseleccionan_ninguna_opcion():
    assert "— elegir —" in revisar.PAGINA
