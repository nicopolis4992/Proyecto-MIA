"""
Repositorio provisional en SQLite.

Guarda lo minimo que el prototipo necesita para funcionar entre mensajes:
- sesiones: estado de la conversacion por numero de WhatsApp.
- citas: la cita propuesta con los campos de SCRUM-74 y su estado
  (pendiente_aprobacion -> aprobada / rechazada -> confirmada).
- eventos_cita: trazabilidad de cada transicion (quien, cuando, que).
- mensajes_salientes: cola de mensajes que no se pudieron enviar (SCRUM-87).
- mensajes_procesados: deduplicacion de webhooks reintentados por Meta.

Cuando el esquema relacional de Supabase (SCRUM-74) este listo, se
reemplaza esta clase por una con la misma interfaz publica; los agentes no
deberian notar el cambio.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import RUTA_DB, ahora

ESTADOS_CITA = (
    "pendiente_aprobacion",
    "aprobada",
    "rechazada",
    "confirmada",
    "cancelada",
)

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS sesiones (
    telefono TEXT PRIMARY KEY,
    datos TEXT NOT NULL,
    actualizada TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS citas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_telefono TEXT NOT NULL,
    cliente_nombre TEXT,
    mascotas TEXT NOT NULL,
    fecha_hora TEXT,
    modalidad TEXT NOT NULL,
    zona TEXT,
    sector TEXT,
    cotizacion TEXT,
    total_acordado REAL,
    origen TEXT DEFAULT 'whatsapp',
    descuento_aplicado TEXT,
    requiere_revision_manual INTEGER DEFAULT 0,
    estado TEXT NOT NULL,
    ciclo_aprobacion INTEGER DEFAULT 1,
    msg_aprobacion_id TEXT,
    fecha_registro TEXT NOT NULL,
    actualizada TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eventos_cita (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cita_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    detalle TEXT,
    fecha TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mensajes_salientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    destino TEXT NOT NULL,
    cuerpo TEXT NOT NULL,
    estado TEXT NOT NULL,
    intentos INTEGER DEFAULT 0,
    ultimo_error TEXT,
    creado TEXT NOT NULL,
    actualizado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mensajes_procesados (
    wa_id TEXT PRIMARY KEY,
    fecha TEXT NOT NULL
);
"""

_CAMPOS_JSON = ("mascotas", "cotizacion", "descuento_aplicado")


def _ts() -> str:
    return ahora().isoformat(timespec="seconds")


class Repositorio:
    def __init__(self, ruta: str | Path = RUTA_DB):
        ruta = str(ruta)
        if ruta != ":memory:":
            Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        # FastAPI ejecuta tareas en segundo plano en otros hilos: una sola
        # conexion protegida por lock es suficiente para el volumen del piloto.
        self._con = sqlite3.connect(ruta, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._con.executescript(_ESQUEMA)

    def _ejecutar(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._con.execute(sql, params)
            self._con.commit()
            return cur

    # -- sesiones -----------------------------------------------------------

    def obtener_sesion(self, telefono: str) -> dict:
        fila = self._ejecutar(
            "SELECT datos FROM sesiones WHERE telefono = ?", (telefono,)
        ).fetchone()
        return json.loads(fila["datos"]) if fila else {}

    def guardar_sesion(self, telefono: str, datos: dict) -> None:
        self._ejecutar(
            "INSERT INTO sesiones (telefono, datos, actualizada) VALUES (?, ?, ?) "
            "ON CONFLICT(telefono) DO UPDATE SET datos = excluded.datos, "
            "actualizada = excluded.actualizada",
            (telefono, json.dumps(datos, ensure_ascii=False, default=str), _ts()),
        )

    def borrar_sesion(self, telefono: str) -> None:
        self._ejecutar("DELETE FROM sesiones WHERE telefono = ?", (telefono,))

    # -- citas --------------------------------------------------------------

    def crear_cita(self, **campos: Any) -> int:
        campos.setdefault("estado", "pendiente_aprobacion")
        campos["fecha_registro"] = campos["actualizada"] = _ts()
        campos = self._serializar(campos)
        columnas = ", ".join(campos)
        marcas = ", ".join("?" for _ in campos)
        cur = self._ejecutar(
            f"INSERT INTO citas ({columnas}) VALUES ({marcas})", tuple(campos.values())
        )
        cita_id = cur.lastrowid
        self.registrar_evento(cita_id, "creada", {"estado": campos["estado"]})
        return cita_id

    def obtener_cita(self, cita_id: int) -> dict | None:
        fila = self._ejecutar("SELECT * FROM citas WHERE id = ?", (cita_id,)).fetchone()
        return self._deserializar(fila) if fila else None

    def actualizar_cita(self, cita_id: int, **campos: Any) -> None:
        if "estado" in campos and campos["estado"] not in ESTADOS_CITA:
            raise ValueError(f"Estado de cita invalido: {campos['estado']}")
        campos["actualizada"] = _ts()
        campos = self._serializar(campos)
        asignaciones = ", ".join(f"{c} = ?" for c in campos)
        self._ejecutar(
            f"UPDATE citas SET {asignaciones} WHERE id = ?",
            (*campos.values(), cita_id),
        )

    def cita_por_mensaje_aprobacion(self, wa_msg_id: str) -> dict | None:
        fila = self._ejecutar(
            "SELECT * FROM citas WHERE msg_aprobacion_id = ?", (wa_msg_id,)
        ).fetchone()
        return self._deserializar(fila) if fila else None

    def citas_por_estado(self, estado: str) -> list[dict]:
        filas = self._ejecutar(
            "SELECT * FROM citas WHERE estado = ? ORDER BY id", (estado,)
        ).fetchall()
        return [self._deserializar(f) for f in filas]

    def registrar_evento(self, cita_id: int, tipo: str, detalle: Any = None) -> None:
        self._ejecutar(
            "INSERT INTO eventos_cita (cita_id, tipo, detalle, fecha) VALUES (?, ?, ?, ?)",
            (cita_id, tipo, json.dumps(detalle, ensure_ascii=False, default=str), _ts()),
        )

    def eventos_de_cita(self, cita_id: int) -> list[dict]:
        filas = self._ejecutar(
            "SELECT tipo, detalle, fecha FROM eventos_cita WHERE cita_id = ? ORDER BY id",
            (cita_id,),
        ).fetchall()
        return [
            {"tipo": f["tipo"], "detalle": json.loads(f["detalle"]), "fecha": f["fecha"]}
            for f in filas
        ]

    @staticmethod
    def _serializar(campos: dict) -> dict:
        salida = {}
        for k, v in campos.items():
            if k in _CAMPOS_JSON and v is not None:
                v = json.dumps(v, ensure_ascii=False, default=str)
            elif isinstance(v, datetime):
                v = v.isoformat(timespec="minutes")
            elif isinstance(v, bool):
                v = int(v)
            salida[k] = v
        return salida

    @staticmethod
    def _deserializar(fila: sqlite3.Row) -> dict:
        d = dict(fila)
        for k in _CAMPOS_JSON:
            if d.get(k):
                d[k] = json.loads(d[k])
        d["requiere_revision_manual"] = bool(d.get("requiere_revision_manual"))
        return d

    # -- cola de salida (SCRUM-87) -----------------------------------------

    def encolar_mensaje(self, destino: str, cuerpo: str, error: str) -> int:
        ts = _ts()
        cur = self._ejecutar(
            "INSERT INTO mensajes_salientes "
            "(destino, cuerpo, estado, intentos, ultimo_error, creado, actualizado) "
            "VALUES (?, ?, 'pendiente', 1, ?, ?, ?)",
            (destino, cuerpo, error, ts, ts),
        )
        return cur.lastrowid

    def mensajes_pendientes(self, max_intentos: int) -> list[dict]:
        filas = self._ejecutar(
            "SELECT * FROM mensajes_salientes WHERE estado = 'pendiente' "
            "AND intentos < ? ORDER BY id",
            (max_intentos,),
        ).fetchall()
        return [dict(f) for f in filas]

    def marcar_mensaje(self, msg_id: int, estado: str, error: str | None = None) -> None:
        self._ejecutar(
            "UPDATE mensajes_salientes SET estado = ?, intentos = intentos + 1, "
            "ultimo_error = COALESCE(?, ultimo_error), actualizado = ? WHERE id = ?",
            (estado, error, _ts(), msg_id),
        )

    # -- deduplicacion de webhooks -----------------------------------------

    def marcar_procesado(self, wa_id: str) -> bool:
        """Devuelve True si el mensaje es nuevo, False si ya se proceso."""
        try:
            self._ejecutar(
                "INSERT INTO mensajes_procesados (wa_id, fecha) VALUES (?, ?)",
                (wa_id, _ts()),
            )
            return True
        except sqlite3.IntegrityError:
            return False


_repo: Repositorio | None = None


def obtener_repositorio() -> Repositorio:
    global _repo
    if _repo is None:
        _repo = Repositorio()
    return _repo
