"""
Panel web: demo conversacional + agenda + dashboard de la propietaria.

    GET  /panel                      pagina (HTML)
    GET  /panel/api/dashboard        indicadores y citas (?fuente=demo|real)
    GET  /panel/api/cita/{id}        detalle con cotizacion y trazabilidad
    GET  /panel/api/chat             conversacion de la demo
    POST /panel/api/mensaje          envia un mensaje como clienta o propietaria (demo)
    POST /panel/api/ejemplo          carga citas SIMULADAS en la base de demo
    POST /panel/api/reiniciar        borra la base de demo

La demo corre el MISMO orquestador que WhatsApp (NLU, RAG, foto, agenda,
aprobacion) contra una base aparte (data/demo.sqlite3); los mensajes
salientes se muestran en pantalla en vez de enviarse por Meta. Si Google
Calendar esta configurado, las citas aprobadas en la demo tambien aparecen
en el calendario real.

Acceso: con DEMO_CLAVE definida se exige la clave (cabecera X-Panel-Clave o
?clave=). Sin DEMO_CLAVE, el panel solo responde desde la propia maquina.
"""

from __future__ import annotations

import base64
import itertools
import os
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.config import RAIZ_APP, ZONA_HORARIA
from app.mensajeria import MensajeroMemoria
from app.panel import datos
from app.persistencia.repositorio import Repositorio, obtener_repositorio

router = APIRouter(prefix="/panel")

CLIENTE_DEMO = "593900000099"
PROPIETARIA_DEMO = "593900000001"
RUTA_DB_DEMO = RAIZ_APP.parent / "data" / "demo.sqlite3"
HTML = Path(__file__).parent / "static" / "index.html"


def _autorizar(request: Request) -> None:
    clave = os.getenv("DEMO_CLAVE", "")
    if clave:
        enviada = request.headers.get("x-panel-clave") or request.query_params.get("clave")
        if enviada != clave:
            raise HTTPException(status_code=401, detail="Clave del panel incorrecta")
    elif request.client and request.client.host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(status_code=403, detail="Defina DEMO_CLAVE para usar el panel en remoto")


class _MensajeroDemo(MensajeroMemoria):
    """Captura lo que el bot envia a terceros y lo agrega al chat de la demo."""

    def __init__(self, demo: "Demo"):
        super().__init__()
        self.demo = demo

    def enviar(self, destino: str, texto: str) -> str | None:
        msg_id = super().enviar(destino, texto)
        self.demo.agregar(destino, "bot", texto, msg_id)
        return msg_id


class Demo:
    def __init__(self):
        self.lock = threading.Lock()
        self.ids = itertools.count(1)
        self._iniciar()

    def _iniciar(self):
        self.repo = Repositorio(RUTA_DB_DEMO)
        self.chat: list[dict] = []
        self.mensajero = _MensajeroDemo(self)
        self.grafo = None
        self.deps = None

    def _grafo(self):
        if self.grafo is None:
            from app.agents import orchestrator_graph as og

            self.deps = og.crear_dependencias(repo=self.repo, mensajero=self.mensajero,
                                              propietaria=PROPIETARIA_DEMO)
            self.grafo = og.construir_grafo(self.deps)
        return self.grafo

    def agregar(self, telefono: str, autor: str, texto: str, msg_id: str | None = None, imagen: str | None = None):
        self.chat.append({
            "n": next(self.ids), "canal": "propietaria" if telefono == PROPIETARIA_DEMO else "cliente",
            "autor": autor, "texto": texto, "imagen": imagen, "msg_id": msg_id,
            "hora": datetime.now(ZONA_HORARIA).strftime("%H:%M"),
        })

    def mensaje(self, canal: str, texto: str, imagen_b64: str | None) -> None:
        from app.agents.orchestrator_graph import procesar_mensaje

        telefono = PROPIETARIA_DEMO if canal == "propietaria" else CLIENTE_DEMO
        imagen = base64.b64decode(imagen_b64.split(",")[-1]) if imagen_b64 else None
        self.agregar(telefono, "persona", texto, imagen=imagen_b64)
        # La propietaria responde citando el ultimo resumen que recibio.
        id_citado = None
        if canal == "propietaria":
            ids = [i for d, _, i in self.mensajero.enviados if d == PROPIETARIA_DEMO]
            id_citado = ids[-1] if ids else None
        respuesta = procesar_mensaje(telefono, texto, imagen, id_citado, grafo=self._grafo())
        if respuesta:
            self.agregar(telefono, "bot", respuesta)

    def reiniciar(self):
        # Se vacian las tablas en vez de borrar el archivo: en Windows el
        # archivo puede estar bloqueado por otra conexion.
        self.repo.vaciar()
        self.chat.clear()
        self.mensajero.enviados.clear()


_demo: Demo | None = None


def demo() -> Demo:
    global _demo
    if _demo is None:
        _demo = Demo()
    return _demo


def _repo(fuente: str):
    return obtener_repositorio() if fuente == "real" else demo().repo


@router.get("")
def pagina(request: Request):
    _autorizar(request)
    return FileResponse(HTML, media_type="text/html")


@router.get("/api/dashboard")
def dashboard(request: Request, fuente: str = "demo"):
    _autorizar(request)
    return datos.resumen(_repo(fuente))


@router.get("/api/cita/{cita_id}")
def cita(request: Request, cita_id: int, fuente: str = "demo"):
    _autorizar(request)
    d = datos.detalle_cita(_repo(fuente), cita_id)
    if d is None:
        raise HTTPException(status_code=404)
    return d


@router.get("/api/chat")
def chat(request: Request):
    _autorizar(request)
    return demo().chat


@router.post("/api/mensaje")
async def mensaje(request: Request):
    _autorizar(request)
    cuerpo = await request.json()
    canal = cuerpo.get("canal", "cliente")
    d = demo()
    import asyncio

    def _correr():
        with d.lock:
            d.mensaje(canal, cuerpo.get("texto", ""), cuerpo.get("imagen"))

    await asyncio.to_thread(_correr)
    return d.chat


@router.post("/api/ejemplo")
def ejemplo(request: Request):
    _autorizar(request)
    from app.cotizacion.cotizador import Cotizador

    d = demo()
    with d.lock:
        n = datos.cargar_ejemplo(d.repo, Cotizador())
    return {"creadas": n}


@router.post("/api/reiniciar")
def reiniciar(request: Request):
    _autorizar(request)
    d = demo()
    with d.lock:
        d.reiniciar()
    return {"ok": True}
