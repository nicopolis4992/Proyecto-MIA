"""
SCRUM-87: ante un error simulado de la API de WhatsApp el sistema reintenta,
registra el fallo y no pierde el mensaje (cola de salida).
"""

import httpx
import pytest

from app import config, whatsapp_client
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

    monkeypatch.setattr(config, "PROPIETARIA_WHATSAPP", "593900000001")
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


# -- SCRUM-86: respaldo por correo para la propietaria ------------------------

class SMTPFalso:
    enviados: list = []

    def __init__(self, host, puerto, timeout=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, usuario, clave):
        pass

    def send_message(self, msg):
        SMTPFalso.enviados.append(msg)


@pytest.fixture
def correo_configurado(monkeypatch):
    from app.notificaciones import correo
    SMTPFalso.enviados = []
    for k, v in {"CORREO_USUARIO": "bot@x.com", "CORREO_CLAVE": "c", "CORREO_PROPIETARIA": "lina@x.com"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(correo.smtplib, "SMTP", SMTPFalso)
    monkeypatch.setattr(config, "PROPIETARIA_WHATSAPP", "593900000001")
    return SMTPFalso.enviados


def test_error_permanente_hacia_la_propietaria_se_envia_por_correo(monkeypatch, correo_configurado):
    def handler(request):
        return httpx.Response(401, json={"error": {"code": whatsapp_client.TOKEN_INVALIDO, "message": "x"}})
    monkeypatch.setattr(whatsapp_client.httpx, "Client",
                        lambda **kw: CLIENTE_HTTP_REAL(transport=httpx.MockTransport(handler), **kw))
    repo = Repositorio(":memory:")
    MensajeroWhatsApp(repo).enviar("593900000001", "🐾 Nueva cita #3 por aprobar\nCliente: Rosa")
    [msg] = correo_configurado
    assert msg["To"] == "lina@x.com" and "Nueva cita #3" in msg["Subject"]
    assert "Nueva cita #3" in msg.get_content() and "listo #5" in msg.get_content()
    assert "enviado por correo" in repo.mensajes_no_entregados()[0]["ultimo_error"]


def test_a_un_cliente_no_se_le_manda_correo(monkeypatch, correo_configurado):
    _error_meta(monkeypatch, whatsapp_client.NO_PERMITIDO_EN_PRUEBAS)
    MensajeroWhatsApp(Repositorio(":memory:")).enviar("593911111111", "hola")
    assert correo_configurado == []


def test_cola_agotada_hacia_la_propietaria_se_envia_por_correo(monkeypatch, correo_configurado):
    _simular(monkeypatch, *([503] * 20))
    repo = Repositorio(":memory:")
    repo.encolar_mensaje("593900000001", "🐾 Nueva cita #4 por aprobar", "caida")
    for _ in range(5):
        reintentar_pendientes(repo)
    assert len(correo_configurado) == 1
    assert repo.mensajes_no_entregados()[0]["estado"] == "fallido"


def test_sin_configuracion_no_se_intenta_enviar(monkeypatch):
    from app.notificaciones import correo
    for k in ("CORREO_USUARIO", "CORREO_CLAVE", "CORREO_PROPIETARIA"):
        monkeypatch.delenv(k, raising=False)
    assert correo.enviar_correo("x", "y") is False


# -- regla de 24 h: plantilla + entrega al responder ---------------------------

def _meta_con_ventana(monkeypatch, abierta: dict):
    """Simula Meta: texto a un numero sin ventana -> 131047; plantillas siempre salen."""
    enviados = []

    def handler(request):
        cuerpo = __import__("json").loads(request.content)
        enviados.append(cuerpo)
        if cuerpo["type"] == "text" and not abierta.get(cuerpo["to"]):
            return httpx.Response(400, json={"error": {"code": whatsapp_client.FUERA_DE_VENTANA, "message": "x"}})
        return httpx.Response(200, json={"messages": [{"id": f"wamid.{len(enviados)}"}]})

    monkeypatch.setattr(whatsapp_client.httpx, "Client",
                        lambda **kw: CLIENTE_HTTP_REAL(transport=httpx.MockTransport(handler), **kw))
    return enviados


def test_fuera_de_ventana_envia_plantilla_y_entrega_al_responder(monkeypatch):
    from app.mensajeria import entregar_en_espera

    monkeypatch.setattr(config, "PROPIETARIA_WHATSAPP", "593900000001")
    monkeypatch.setattr(config, "PLANTILLA_PROPIETARIA", "solicitud_cita")
    ventana: dict = {}
    enviados = _meta_con_ventana(monkeypatch, ventana)
    repo = Repositorio(":memory:")
    resumen = "🐾 Nueva cita #7 por aprobar\nCliente: Rosa\n• Luna: Baño Completo\n\nResponde a ESTE mensaje"

    msg_id = MensajeroWhatsApp(repo).enviar("593900000001", resumen)
    assert msg_id                                   # el id de la plantilla: citarla sirve para aprobar
    plantilla = enviados[-1]["template"]
    assert plantilla["name"] == "solicitud_cita"
    parametro = plantilla["components"][0]["parameters"][0]["text"]
    assert "\n" not in parametro and "Nueva cita #7" in parametro
    assert repo.mensajes_no_entregados() == []      # no es un fallo: esta en espera

    ventana["593900000001"] = True                  # la propietaria escribe
    assert entregar_en_espera(repo, "593900000001") == 1
    assert enviados[-1]["text"]["body"] == resumen
    assert entregar_en_espera(repo, "593900000001") == 0


def test_sin_plantilla_configurada_sigue_el_camino_anterior(monkeypatch):
    monkeypatch.setattr(config, "PROPIETARIA_WHATSAPP", "593900000001")
    monkeypatch.setattr(config, "PLANTILLA_CLIENTE", "")
    _meta_con_ventana(monkeypatch, {"593900000001": True})
    repo = Repositorio(":memory:")
    assert MensajeroWhatsApp(repo).enviar("593900000099", "¡Listo! Queda agendado") is None
    assert repo.mensajes_no_entregados()[0]["estado"] == "no_entregado"


def test_resumen_corto_para_parametro_de_plantilla():
    from app.mensajeria import resumen_corto
    assert resumen_corto("a\n\n• b\t c     d\ne\nf") == "a · b c d · e"
    assert len(resumen_corto("x" * 500)) == 160
