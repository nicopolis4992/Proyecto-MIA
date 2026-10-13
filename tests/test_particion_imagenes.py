"""SCRUM-101/102: particion agrupada por mascota y estratificada por las clases raras."""

from entrenamiento.clasificador_imagen.preetiquetar import particion_estratificada


def test_las_clases_raras_llegan_a_validacion_y_prueba_sin_repetir_mascotas():
    filas = []
    for i in range(60):  # comunes: pequeno, pelo de maquina, 2 fotos por mascota
        filas += [{"id_mascota_prov": f"C{i}", "tamano": "pequeno", "grupo": "A_maquina", "estado": "sin_motas"}] * 2
    for i in range(6):   # raras: grandes de doble capa
        filas += [{"id_mascota_prov": f"R{i}", "tamano": "grande", "grupo": "B_deslanado", "estado": ""}] * 2
    asignacion = particion_estratificada(filas)
    assert set(asignacion) == {f["id_mascota_prov"] for f in filas}          # cada mascota en UN conjunto
    raras = [asignacion[f"R{i}"] for i in range(6)]
    assert "val" in raras and "test" in raras and "train" in raras
    assert particion_estratificada(filas) == asignacion                      # reproducible
