import os
from unittest.mock import patch

os.environ["WHATSAPP_VERIFY_TOKEN"] = "test-token"
os.environ["WHATSAPP_ACCESS_TOKEN"] = "fake-access-token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "fake-phone-id"
os.environ["GEMINI_API_KEY"] = "fake-gemini-key"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def _payload(sender: str, mensaje: dict) -> dict:
    """Payload simplificado, con la misma forma que envía WhatsApp Cloud API."""
    return {"entry": [{"changes": [{"value": {"messages": [{"from": sender, **mensaje}]}}]}]}


def _texto(sender, text, wa_id="wamid.1", context=None):
    m = {"id": wa_id, "type": "text", "text": {"body": text}}
    if context:
        m["context"] = {"id": context}
    return _payload(sender, m)


@patch("app.mensajeria.send_text_message")
@patch("app.main.procesar_mensaje")
def test_webhook_responde_a_mensaje_de_texto(mock_procesar, mock_send):
    mock_procesar.return_value = "¡Hola! Gracias por escribirnos."

    response = client.post("/webhook", json=_texto("593999999999", "Hola, quiero una cita", "wamid.t1"))

    assert response.status_code == 200
    mock_procesar.assert_called_once_with("593999999999", "Hola, quiero una cita", None, None)
    mock_send.assert_called_once_with(to="593999999999", body="¡Hola! Gracias por escribirnos.")


@patch("app.mensajeria.send_text_message")
@patch("app.main.procesar_mensaje")
def test_webhook_pasa_el_mensaje_citado(mock_procesar, mock_send):
    mock_procesar.return_value = None
    client.post("/webhook", json=_texto("593900000001", "listo", "wamid.t2", context="wamid.cita"))
    mock_procesar.assert_called_once_with("593900000001", "listo", None, "wamid.cita")
    mock_send.assert_not_called()


@patch("app.main.download_media", return_value=b"jpeg")
@patch("app.mensajeria.send_text_message")
@patch("app.main.procesar_mensaje", return_value="cotizacion")
def test_webhook_descarga_y_procesa_imagenes(mock_procesar, mock_send, mock_media):
    payload = _payload("593", {"id": "wamid.t3", "type": "image", "image": {"id": "media9", "caption": "mi perro"}})
    client.post("/webhook", json=payload)
    mock_media.assert_called_once_with("media9")
    mock_procesar.assert_called_once_with("593", "mi perro", b"jpeg", None)


@patch("app.mensajeria.send_text_message")
@patch("app.main.procesar_mensaje", return_value="ok")
def test_webhook_ignora_reintentos_de_meta(mock_procesar, mock_send):
    """Meta reenvía el mismo webhook si no recibe 200 a tiempo: no responder dos veces."""
    client.post("/webhook", json=_texto("593", "hola", "wamid.dup"))
    client.post("/webhook", json=_texto("593", "hola", "wamid.dup"))
    assert mock_procesar.call_count == 1


@patch("app.mensajeria.send_text_message")
@patch("app.main.procesar_mensaje")
def test_webhook_ignora_eventos_sin_mensajes(mock_procesar, mock_send):
    """Ej: notificaciones de estado (entregado/leído), no mensajes nuevos."""
    payload = {"entry": [{"changes": [{"value": {"statuses": [{"status": "delivered"}]}}]}]}

    response = client.post("/webhook", json=payload)

    assert response.status_code == 200
    mock_procesar.assert_not_called()
    mock_send.assert_not_called()


@patch("app.mensajeria.send_text_message")
@patch("app.main.procesar_mensaje")
def test_webhook_no_revienta_con_payload_invalido(mock_procesar, mock_send):
    response = client.post("/webhook", json={"algo": "inesperado"})

    assert response.status_code == 200
    mock_procesar.assert_not_called()
    mock_send.assert_not_called()


@patch("app.mensajeria.send_text_message")
@patch("app.main.procesar_mensaje")
def test_webhook_responde_200_aunque_falle_el_procesamiento(mock_procesar, mock_send):
    """Si Gemini o WhatsApp fallan, igual respondemos 200 a Meta (no reintentos)."""
    mock_procesar.side_effect = RuntimeError("Gemini no disponible")

    response = client.post("/webhook", json=_texto("593999999999", "Hola", "wamid.t4"))

    assert response.status_code == 200
    mock_send.assert_not_called()


@patch("app.mensajeria.send_text_message")
@patch("app.main.procesar_mensaje", return_value="ok")
def test_modo_pruebas_solo_atiende_numeros_autorizados(mock_procesar, mock_send, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "MODO", "pruebas")
    monkeypatch.setattr(config, "NUMEROS_PERMITIDOS", {"593911111111"})
    monkeypatch.setattr(config, "PROPIETARIA_WHATSAPP", "593922222222")

    client.post("/webhook", json=_texto("593933333333", "hola", "wamid.p1"))  # cliente real
    mock_procesar.assert_not_called()
    mock_send.assert_not_called()

    client.post("/webhook", json=_texto("593911111111", "hola", "wamid.p2"))  # integrante
    client.post("/webhook", json=_texto("593922222222", "listo", "wamid.p3"))  # "propietaria" de prueba
    assert mock_procesar.call_count == 2


def test_en_reserva_las_descripciones_van_a_agenda_y_las_preguntas_al_rag():
    from types import SimpleNamespace

    from app.agents.orchestrator_graph import enrutar_por_intencion

    def ruta(msg, en_flujo=True):
        return enrutar_por_intencion({"mensaje": msg, "en_flujo_agenda": en_flujo,
                                      "nlu": SimpleNamespace(intencion="consultar")})

    assert ruta("Su pelo le crece y hay que cortárselo") == "agente_agenda"
    assert ruta("¿Cuánto cuesta el deslanado?") == "agente_rag"
    assert ruta("cuanto cobran por el traslado") == "agente_rag"
    assert ruta("Su pelo le crece", en_flujo=False) == "agente_rag"
    assert ruta("y despues de las 3?") == "agente_agenda"
    assert ruta("¿puede en la tarde?") == "agente_agenda"
