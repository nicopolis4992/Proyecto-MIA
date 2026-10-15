"""SCRUM-105: formulario de Google para el estandar de oro a distancia."""

import csv

from entrenamiento.clasificador_imagen import formulario_ciego as fc


def _manifiesto(tmp_path):
    ruta = tmp_path / "manifiesto.csv"
    with open(ruta, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["ruta", "mascota_id", "tamano", "grupo", "estado", "particion"])
        w.writeheader()
        for i in range(6):
            w.writerow({"ruta": f"imagenes/FB_M{i:03d}_antes.jpg", "mascota_id": f"M{i}", "tamano": "pequeno",
                        "grupo": "A_maquina", "estado": "sin_motas", "particion": "test" if i < 3 else "train"})
    return ruta


def test_script_y_respuestas_del_formulario(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "READ", tmp_path)
    manifiesto = _manifiesto(tmp_path)
    gs = tmp_path / "form.gs"
    assert fc.generar_script(manifiesto, "Carpeta/imagenes", gs) == 3
    codigo = gs.read_text(encoding="utf-8")
    assert "function crearFormulario" in codigo and '"Carpeta/imagenes"' in codigo
    assert "FB_M000_antes.jpg" in codigo and 'setName(foto[0] + ".jpg")' in codigo   # nombre neutro en el form

    # CSV como el que exporta Google Forms (una fila por respuesta)
    orden = list(csv.DictReader(open(tmp_path / "estandar_oro_propietaria.csv", encoding="utf-8-sig")))
    cols = ["Marca temporal"] + [f"Foto {i} · {t}" for i in range(1, 4) for t in fc.PREGUNTA.values()]
    fila = {"Marca temporal": "15/10/2026 10:00:00"}
    for i in range(1, 4):
        fila[f"Foto {i} · Tamaño"] = "Grande (más de 18 kg)" if i == 1 else "Pequeño (hasta 9 kg)"
        fila[f"Foto {i} · Tipo de pelo"] = list(fc.OPCIONES["grupo"])[0]
        fila[f"Foto {i} · Estado del pelo"] = "No se ve en esta foto"
    respuestas = tmp_path / "respuestas.csv"
    with open(respuestas, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerow(fila)
    assert fc.importar(respuestas, manifiesto) == (3, 3)
    oro = list(csv.DictReader(open(tmp_path / "estandar_oro_propietaria.csv", encoding="utf-8-sig")))
    assert oro[0]["ruta"] == orden[0]["ruta"] and oro[0]["tamano"] == "grande"
    assert all(f["revisado"] == "si" and f["grupo"] == "A_maquina" and f["estado"] == "" for f in oro)
