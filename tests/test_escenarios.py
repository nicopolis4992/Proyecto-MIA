"""
Escenarios completos reproducidos desde grabaciones de Gemini (sin costo).

Si un escenario no está grabado se salta: grabarlo con
`python -m scripts.escenarios <nombre>` (gasta créditos una sola vez).
Si un prompt cambia, la reproducción falla con GrabacionFaltante: volver a
grabar ese escenario.
"""

import os
from types import SimpleNamespace

import pytest

from app.llm_cache import ClienteCacheado, GrabacionFaltante
from scripts import escenarios


@pytest.fixture(autouse=True)
def entorno_limpio():
    antes = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(antes)


def _correr(nombre):
    if not (escenarios.GRABACIONES / nombre).exists():
        pytest.skip(f"Escenario '{nombre}' sin grabar: python -m scripts.escenarios {nombre}")
    demo = escenarios.correr(nombre, solo_lectura=True, mostrar=False)
    # Un error (p. ej. grabacion faltante) se convierte en MENSAJE_ERROR: no debe aparecer.
    from app.agents.orchestrator_graph import MENSAJE_ERROR
    assert not any(m["texto"] == MENSAJE_ERROR for m in demo.chat), (
        f"El escenario '{nombre}' tuvo errores: regrabar con python -m scripts.escenarios {nombre}")
    return demo


def _textos(demo, canal):
    return [m["texto"] for m in demo.chat if m["canal"] == canal and m["autor"] == "bot"]


def test_cache_graba_una_vez_y_luego_reproduce(tmp_path):
    llamadas = []
    real = SimpleNamespace(models=SimpleNamespace(
        generate_content=lambda **kw: llamadas.append(kw) or SimpleNamespace(text="hola"),
        embed_content=lambda **kw: SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1, 0.2])])))
    c = ClienteCacheado(real, tmp_path)
    assert c.models.generate_content(model="m", contents="x").text == "hola"
    assert c.models.generate_content(model="m", contents="x").text == "hola"
    assert len(llamadas) == 1                                       # la segunda vino del disco
    assert c.models.embed_content(model="e", contents=["a"]).embeddings[0].values == [0.1, 0.2]
    offline = ClienteCacheado(None, tmp_path, solo_lectura=True)
    assert offline.models.generate_content(model="m", contents="x").text == "hola"
    with pytest.raises(GrabacionFaltante):
        offline.models.generate_content(model="m", contents="otra cosa")


def test_escenario_mestiza_puerta_a_puerta():
    demo = _correr("mestiza_puerta_a_puerta")
    [cita] = demo.repo.todas_las_citas()
    assert cita["estado"] == "confirmada" and cita["modalidad"] == "puerta_a_puerta"
    assert any("restricción de circulación" in t for t in _textos(demo, "cliente"))


def test_escenario_reprogramacion():
    demo = _correr("reprogramacion")
    cliente = _textos(demo, "cliente")
    assert any("Para ese día tengo libre" in t for t in cliente)                 # horarios reales
    assert any("💬 Respuesta de la propietaria" in t for t in cliente)          # relevo de consulta
    assert any("le propone este ajuste" in t for t in cliente)                  # propuesta al cliente
    assert any("busquemos otro horario" in t for t in cliente)                  # reprogramacion
    [cita] = demo.repo.todas_las_citas()
    assert cita["estado"] == "confirmada" and cita["total_acordado"] == 22


def test_escenario_preferencia_tarde():
    demo = _correr("preferencia_tarde")
    ofertas = [t for t in _textos(demo, "cliente") if " a las " in t and "1." in t]
    tarde = ofertas[1]
    horas = [l.split(" a las ")[1] for l in tarde.splitlines() if " a las " in l]
    assert all(h >= "12:00" for h in horas)


def test_escenario_pedido_especial_sin_precio():
    demo = _correr("pedido_especial")
    respuestas = _textos(demo, "cliente")
    assert sum("Anoto su pedido" in t for t in respuestas) == 1                    # se anuncia una vez
    assert any("le confirma el precio con ese cambio" in t or "lo valida la propietaria" in t for t in respuestas)
    assert not any("USD" in t for t in respuestas[1:])                           # sin precio tras el pedido
    [cita] = demo.repo.todas_las_citas()
    assert cita["pedido_especial"]
    assert any("Pedido especial" in t for t in _textos(demo, "propietaria"))
