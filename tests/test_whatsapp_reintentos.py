"""
SCRUM-87: ante un error simulado de la API de WhatsApp el sistema reintenta,
registra el fallo y no pierde el mensaje (cola de salida).
"""

import httpx
import pytest

from app import whatsapp_client
from app.mensajeria import MensajeroWhatsApp, reintentar_pendientes
from app.persistencia.repositorio import Repositorio
from app.whatsapp_client import ErrorWhatsApp, send_text_message

CLIENTE_HTTP_REAL = httpx.Client


@pytest.fixture(autouse=True)
def credenciales(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "x")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "y")
    monkeypatch.setattr(whatsapp_client, "ESPERA_BASE_S", 0)


def _simular(monkeypatch, *respuestas):
    """Cada elemento es un status HTTP o una excepcion de transporte."""
    pendientes, llamadas = list(respuestas), []

    def handler(request):
        llamadas.append(request)
        r = pendientes.pop(0)
        if isinstance(r, Exception):
            raise r
        return httpx.Response(r, json={"messages": [{"id": "wamid.ok"}]} if r == 200 else {"error": {}})

    monkeypatch.setattr(whatsapp_client.httpx, "Client",
                        lambda **kw: CLIENTE_HTTP_REAL(transport=httpx.MockTransport(handler), **kw))
    return llamadas


def test_reintenta_ante_503_y_devuelve_id(monkeypatch):
    llamadas = _simular(monkeypatch, 503, 200)
    assert send_text_message("593", "hola") == "wamid.ok"
    assert len(llamadas) == 2


def test_reintenta_ante_caida_de_red(monkeypatch):
    llamadas = _simular(monkeypatch, httpx.ConnectError("sin red"), 200)
    assert send_text_message("593", "hola") == "wamid.ok"
    assert len(llamadas) == 2


def test_no_reintenta_error_permanente(monkeypatch):
    llamadas = _simular(monkeypatch, 400)
    with pytest.raises(ErrorWhatsApp) as exc:
        send_text_message("593", "hola")
    assert not exc.value.transitorio and len(llamadas) == 1


def test_mensaje_fallido_queda_en_cola_y_se_reenvia(monkeypatch):
    repo = Repositorio(":memory:")
    _simular(monkeypatch, 503, 503, 503)
    assert MensajeroWhatsApp(repo).enviar("593", "su cita esta confirmada") is None
    [pendiente] = repo.mensajes_pendientes(5)
    assert pendiente["cuerpo"] == "su cita esta confirmada" and "503" in pendiente["ultimo_error"]

    _simular(monkeypatch, 200)
    assert reintentar_pendientes(repo) == {"enviados": 1, "fallidos": 0}
    assert repo.mensajes_pendientes(5) == []


def _error_meta(monkeypatch, codigo, status=400):
    def handler(request):
        destino = __import__("json").loads(request.content)["to"]
        if destino == "593900000001":  # la propietaria si recibe
            return httpx.Response(200, json={"messages": [{"id": "wamid.prop"}]})
        return httpx.Response(status, json={"error": {"code": codigo, "message": "x"}})

    monkeypatch.setattr(whatsapp_client.httpx, "Client",
                        lambda **kw: CLIENTE_HTTP_REAL(transport=httpx.MockTransport(handler), **kw))


def test_fuera_de_ventana_24h_no_se_reintenta_y_avisa_a_la_propietaria(monkeypatch):
    from app import mensajeria

    monkeypatch.setattr(mensajeria, "PROPIETARIA_WHATSAPP", "593900000001")
    _error_meta(monkeypatch, whatsapp_client.FUERA_DE_VENTANA)
    repo = Repositorio(":memory:")
    assert MensajeroWhatsApp(repo).enviar("593900000099", "¡Listo! Queda agendado Toby…") is None
    [m] = repo.mensajes_no_entregados()
    assert m["estado"] == "no_entregado" and "24 h" in m["ultimo_error"]
    assert repo.mensajes_pendientes(5) == []          # no se reintenta: no serviria


def test_numero_fuera_de_la_lista_de_prueba_se_explica(monkeypatch):
    _error_meta(monkeypatch, whatsapp_client.NO_PERMITIDO_EN_PRUEBAS)
    repo = Repositorio(":memory:")
    MensajeroWhatsApp(repo).enviar("593911111111", "hola")
    assert "lista del número de prueba" in repo.mensajes_no_entregados()[0]["ultimo_error"]
