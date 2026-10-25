"""Protecciones contra uso abusivo (incidente de Railway, 22-oct-2026)."""

import hashlib
import hmac
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from conftest import ClienteFalso

from app.limites import ClienteLimitado, LimitadorPorNumero, LimiteGeminiAlcanzado, _ContadorDiario, firma_valida


def test_firma_de_meta():
    cuerpo = b'{"entry": []}'
    firma = "sha256=" + hmac.new(b"secreto", cuerpo, hashlib.sha256).hexdigest()
    assert firma_valida(cuerpo, firma, "secreto")
    assert not firma_valida(cuerpo, firma, "otro")
    assert not firma_valida(cuerpo, None, "secreto")
    assert firma_valida(cuerpo, None, "")          # sin App Secret no se verifica


def test_limite_de_mensajes_por_numero_avisa_una_vez():
    lim = LimitadorPorNumero(limite=3)
    t = datetime(2026, 10, 24, 10, 0)
    assert [lim.permitir("593900000099", t) for _ in range(5)] == ["ok", "ok", "ok", "aviso", "silencio"]
    assert lim.permitir("593900000088", t) == "ok"                       # otro numero no se afecta
    assert lim.permitir("593900000099", t + timedelta(hours=1, minutes=1)) == "ok"   # paso la hora


def test_tope_diario_de_gemini():
    cliente = ClienteLimitado(ClienteFalso("a", "b", "c"), limite=2, contador=_ContadorDiario())
    cliente.models.generate_content(model="m", contents="x")
    cliente.models.generate_content(model="m", contents="y")
    with pytest.raises(LimiteGeminiAlcanzado):
        cliente.models.generate_content(model="m", contents="z")


def test_al_llegar_al_tope_se_pausa_el_bot_y_el_mensaje_va_a_la_propietaria():
    from app.agents import orchestrator_graph as og
    from app.mensajeria import MensajeroMemoria
    from app.persistencia.repositorio import Repositorio

    prop, cli = "593900000001", "593900000099"
    msj, repo = MensajeroMemoria(), Repositorio(":memory:")
    agotado = ClienteLimitado(ClienteFalso(), limite=1, contador=_ContadorDiario())
    agotado.contador.sumar(1, __import__("app.config", fromlist=["ahora"]).ahora().date())
    d = og.crear_dependencias(client=agotado, repo=repo, mensajero=msj, propietaria=prop,
                              agente_rag=lambda m: SimpleNamespace(texto="x", fundamentada=True),
                              clasificador=object(), calendario=False)
    og.configurar(d)
    try:
        r = og.procesar_mensaje(cli, "¿aceptan tarjeta?")
    finally:
        og._deps = og._grafo_compilado = None
    assert repo.bot_pausado() and r is None
    assert "límite diario" in msj.a(prop)[0] and "aceptan tarjeta" in msj.a(prop)[1]
