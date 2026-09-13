import os
from unittest.mock import patch

os.environ["WHATSAPP_VERIFY_TOKEN"] = "test-token"
os.environ["WHATSAPP_ACCESS_TOKEN"] = "fake-access-token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "fake-phone-id"
os.environ["GEMINI_API_KEY"] = "fake-gemini-key"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def _text_message_payload(sender: str, text: str) -> dict:
    """Payload simplificado, con la misma forma que envía WhatsApp Cloud API."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": sender,
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


@patch("app.main.send_text_message")
@patch("app.main.get_reply")
def test_webhook_responde_a_mensaje_de_texto(mock_get_reply, mock_send):
    mock_get_reply.return_value = "¡Hola! Gracias por escribirnos."

    response = client.post(
        "/webhook", json=_text_message_payload("593999999999", "Hola, quiero una cita")
    )

    assert response.status_code == 200
    mock_get_reply.assert_called_once_with("Hola, quiero una cita")
    mock_send.assert_called_once_with(
        to="593999999999", body="¡Hola! Gracias por escribirnos."
    )


@patch("app.main.send_text_message")
@patch("app.main.get_reply")
def test_webhook_ignora_eventos_sin_mensajes(mock_get_reply, mock_send):
    """Ej: notificaciones de estado (entregado/leído), no mensajes nuevos."""
    payload = {"entry": [{"changes": [{"value": {"statuses": [{"status": "delivered"}]}}]}]}

    response = client.post("/webhook", json=payload)

    assert response.status_code == 200
    mock_get_reply.assert_not_called()
    mock_send.assert_not_called()


@patch("app.main.send_text_message")
@patch("app.main.get_reply")
def test_webhook_no_revienta_con_payload_invalido(mock_get_reply, mock_send):
    response = client.post("/webhook", json={"algo": "inesperado"})

    assert response.status_code == 200
    mock_get_reply.assert_not_called()
    mock_send.assert_not_called()


@patch("app.main.send_text_message")
@patch("app.main.get_reply")
def test_webhook_responde_200_aunque_falle_el_envio(mock_get_reply, mock_send):
    """Si Gemini o WhatsApp fallan, igual respondemos 200 a Meta (no reintentos)."""
    mock_get_reply.side_effect = RuntimeError("Gemini no disponible")

    response = client.post(
        "/webhook", json=_text_message_payload("593999999999", "Hola")
    )

    assert response.status_code == 200
    mock_send.assert_not_called()
