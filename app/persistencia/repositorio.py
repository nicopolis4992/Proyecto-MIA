"""
Repositorio provisional en SQLite.

Guarda lo minimo que el prototipo necesita para funcionar entre mensajes:
- sesiones: estado de la conversacion por numero de WhatsApp.
- citas: la cita propuesta con los campos de SCRUM-74 y su estado
  (pendiente_aprobacion -> aprobada / rechazada -> confirmada).
- total_cobrado: lo que la propietaria cobro de verdad (SCRUM-95: desviacion
  entre lo cotizado y lo cobrado).
- eventos_cita: trazabilidad de cada transicion (quien, cuando, que).
- mensajes_salientes: cola de mensajes que no se pudieron enviar (SCRUM-87).
- mensajes_procesados: deduplicacion de webhooks reintentados por Meta.

Datos personales (LOPDP): con las claves configuradas (ver proteccion.py), el
telefono y el nombre del cliente, las sesiones, los detalles de los eventos y
los mensajes en cola se guardan cifrados, y las busquedas por telefono usan un
seudonimo HMAC. `purgar()` borra la informacion operativa vieja.

Cuando el esquema relacional de Supabase (SCRUM-74) este listo, se
reemplaza esta clase por una con la misma interfaz publica; los agentes no
deberian notar el cambio.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import RUTA_DB, ahora
from app.persistencia.proteccion import Proteccion

logger = logging.getLogger("repositorio")

ESTADOS_CITA = (
    "pendiente_aprobacion",   # esperando a la propietaria
    "propuesta_cliente",      # la propietaria cambio hora/precio: espera que el cliente acepte
    "aprobada",
    "rechazada",
    "confirmada",
    "en_reprogramacion",      # el cliente pidio cambiar el horario y esta eligiendo otro
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
    total_cobrado REAL,
    fecha_cobro TEXT,
    origen TEXT DEFAULT 'whatsapp',
    descuento_aplicado TEXT,
    referido_por TEXT,
    pedido_especial TEXT,
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
# Datos de personas que se guardan cifrados (las mascotas y la cotizacion no lo son).
_CAMPOS_CIFRADOS = ("cliente_telefono", "cliente_nombre", "referido_por")


def _ts() -> str:
    return ahora().isoformat(timespec="seconds")


class Repositorio:
    def __init__(self, ruta: str | Path = RUTA_DB, proteccion: Proteccion | None = None):
        self.proteccion = proteccion or Proteccion.desde_entorno()
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
            # Migracion simple: columnas agregadas despues de crear la base.
            columnas = {f[1] for f in self._con.execute("PRAGMA table_info(citas)")}
            for col, tipo in (("pedido_especial", "TEXT"), ("total_cobrado", "REAL"), ("fecha_cobro", "TEXT"),
                             ("referido_por", "TEXT"), ("cliente_nombre", "TEXT")):
                if col not in columnas:
                    self._con.execute(f"ALTER TABLE citas ADD COLUMN {col} {tipo}")
            if "cliente_clave" not in columnas:  # seudonimo del telefono, para buscar sin descifrar
                self._con.execute("ALTER TABLE citas ADD COLUMN cliente_clave TEXT")
            if "destino_clave" not in {f[1] for f in self._con.execute("PRAGMA table_info(mensajes_salientes)")}:
                self._con.execute("ALTER TABLE mensajes_salientes ADD COLUMN destino_clave TEXT")
            self._con.commit()
        self._migrar_proteccion()

    # -- proteccion de datos -------------------------------------------------

    def _migrar_proteccion(self) -> None:
        """Cifra lo que quedo en claro de antes (idempotente). Sin claves, solo completa las claves de busqueda."""
        p = self.proteccion
        with self._lock:
            c = self._con
            for f in c.execute("SELECT id, cliente_telefono, cliente_nombre, referido_por FROM citas "
                               "WHERE cliente_clave IS NULL OR cliente_telefono NOT LIKE 'enc:%'").fetchall():
                tel = p.descifrar(f["cliente_telefono"])
                c.execute("UPDATE citas SET cliente_clave = ?, cliente_telefono = ?, cliente_nombre = ?, "
                          "referido_por = ? WHERE id = ?",
                          (p.seudonimo(tel), p.cifrar(tel), p.cifrar(f["cliente_nombre"]),
                           p.cifrar(f["referido_por"]), f["id"]))
            for f in c.execute("SELECT id, destino, cuerpo FROM mensajes_salientes "
                               "WHERE destino_clave IS NULL OR destino NOT LIKE 'enc:%'").fetchall():
                destino = p.descifrar(f["destino"])
                c.execute("UPDATE mensajes_salientes SET destino_clave = ?, destino = ?, cuerpo = ? WHERE id = ?",
                          (p.seudonimo(destino), p.cifrar(destino), p.cifrar(f["cuerpo"]), f["id"]))
            if p.activa:
                for f in c.execute("SELECT id, detalle FROM eventos_cita WHERE detalle NOT LIKE 'enc:%'").fetchall():
                    c.execute("UPDATE eventos_cita SET detalle = ? WHERE id = ?", (p.cifrar(f["detalle"]), f["id"]))
                for f in c.execute("SELECT telefono, datos, actualizada FROM sesiones "
                                   "WHERE telefono NOT LIKE 'h:%'").fetchall():
                    c.execute("DELETE FROM sesiones WHERE telefono = ?", (f["telefono"],))
                    c.execute("INSERT OR REPLACE INTO sesiones (telefono, datos, actualizada) VALUES (?, ?, ?)",
                              (p.seudonimo(f["telefono"]), p.cifrar(f["datos"]), f["actualizada"]))
            c.commit()

    def purgar(self, dias_sesion: int = 30, dias_dedupe: int = 7, dias_mensajes: int = 30) -> dict:
        """
        Retencion minima (LOPDP, principio de conservacion), como fn_purgar_operacion
        de SCRUM-74: borra conversaciones inactivas, la deduplicacion de webhooks y
        los mensajes ya resueltos. Las citas se conservan: son el registro del negocio.
        """
        def corte(dias):
            return (ahora() - timedelta(days=dias)).isoformat(timespec="seconds")

        sistema = self.proteccion.seudonimo("_sistema")
        with self._lock:
            c = self._con
            borradas = {
                "sesiones": c.execute("DELETE FROM sesiones WHERE actualizada < ? AND telefono NOT IN (?, ?)",
                                      (corte(dias_sesion), "_sistema", sistema)).rowcount,
                "mensajes_procesados": c.execute("DELETE FROM mensajes_procesados WHERE fecha < ?",
                                                 (corte(dias_dedupe),)).rowcount,
                "mensajes_salientes": c.execute(
                    "DELETE FROM mensajes_salientes WHERE actualizado < ? AND estado != 'pendiente'",
                    (corte(dias_mensajes),)).rowcount,
            }
            c.commit()
        if any(borradas.values()):
            logger.info("Purga de datos operativos: %s", borradas)
        return borradas

    def _ejecutar(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._con.execute(sql, params)
            self._con.commit()
            return cur

    # -- sesiones -----------------------------------------------------------

    def obtener_sesion(self, telefono: str) -> dict:
        fila = self._ejecutar(
            "SELECT datos FROM sesiones WHERE telefono = ?", (self.proteccion.seudonimo(telefono),)
        ).fetchone()
        return json.loads(self.proteccion.descifrar(fila["datos"])) if fila else {}

    def guardar_sesion(self, telefono: str, datos: dict) -> None:
        self._ejecutar(
            "INSERT INTO sesiones (telefono, datos, actualizada) VALUES (?, ?, ?) "
            "ON CONFLICT(telefono) DO UPDATE SET datos = excluded.datos, "
            "actualizada = excluded.actualizada",
            (self.proteccion.seudonimo(telefono),
             self.proteccion.cifrar(json.dumps(datos, ensure_ascii=False, default=str)), _ts()),
        )

    # -- interruptor del bot (plan de contingencia, SCRUM-92) ------------------
    # Se guarda como una sesion especial para no agregar otra tabla.

    def bot_pausado(self) -> bool:
        return bool(self.obtener_sesion("_sistema").get("pausado"))

    def pausar_bot(self, pausado: bool) -> None:
        sistema = self.obtener_sesion("_sistema")
        sistema.update(pausado=pausado, cambio=_ts())
        self.guardar_sesion("_sistema", sistema)

    def borrar_sesion(self, telefono: str) -> None:
        self._ejecutar("DELETE FROM sesiones WHERE telefono = ?", (self.proteccion.seudonimo(telefono),))

    # -- citas --------------------------------------------------------------

    def crear_cita(self, **campos: Any) -> int:
        campos.setdefault("estado", "pendiente_aprobacion")
        campos["cliente_clave"] = self.proteccion.seudonimo(campos["cliente_telefono"])
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

    def citas_previas(self, telefono: str, excepto: int | None = None) -> int:
        """Citas confirmadas anteriores del cliente (cliente nuevo o frecuente)."""
        fila = self._ejecutar(
            "SELECT COUNT(*) AS n FROM citas WHERE cliente_clave = ? AND estado = 'confirmada' "
            "AND id != ?", (self.proteccion.seudonimo(telefono), excepto or -1)).fetchone()
        return fila["n"]

    def mascotas_previas(self, telefono: str) -> dict[str, dict]:
        """Ultimos datos de cada mascota del cliente en citas confirmadas (memoria de clientes)."""
        filas = self._ejecutar(
            "SELECT mascotas FROM citas WHERE cliente_clave = ? AND estado = 'confirmada' ORDER BY fecha_hora",
            (self.proteccion.seudonimo(telefono),)).fetchall()
        previas: dict[str, dict] = {}
        for f in filas:
            for m in json.loads(f["mascotas"] or "[]"):
                if m.get("nombre"):
                    previas[m["nombre"].strip().lower()] = m
        return previas

    def vaciar(self) -> None:
        """Borra todos los datos (solo para la base de la demo)."""
        with self._lock:
            for tabla in ("sesiones", "citas", "eventos_cita", "mensajes_salientes", "mensajes_procesados"):
                self._con.execute(f"DELETE FROM {tabla}")
            self._con.execute("DELETE FROM sqlite_sequence")
            self._con.commit()

    def todas_las_citas(self) -> list[dict]:
        filas = self._ejecutar("SELECT * FROM citas ORDER BY fecha_hora").fetchall()
        return [self._deserializar(f) for f in filas]

    def registrar_evento(self, cita_id: int, tipo: str, detalle: Any = None) -> None:
        self._ejecutar(
            "INSERT INTO eventos_cita (cita_id, tipo, detalle, fecha) VALUES (?, ?, ?, ?)",
            (cita_id, tipo, self.proteccion.cifrar(json.dumps(detalle, ensure_ascii=False, default=str)), _ts()),
        )

    def eventos_de_cita(self, cita_id: int) -> list[dict]:
        filas = self._ejecutar(
            "SELECT tipo, detalle, fecha FROM eventos_cita WHERE cita_id = ? ORDER BY id",
            (cita_id,),
        ).fetchall()
        return [
            {"tipo": f["tipo"], "detalle": json.loads(self.proteccion.descifrar(f["detalle"])), "fecha": f["fecha"]}
            for f in filas
        ]

    def _serializar(self, campos: dict) -> dict:
        salida = {}
        for k, v in campos.items():
            if k in _CAMPOS_CIFRADOS:
                v = self.proteccion.cifrar(v)
            elif k in _CAMPOS_JSON and v is not None:
                v = json.dumps(v, ensure_ascii=False, default=str)
            elif isinstance(v, datetime):
                v = v.isoformat(timespec="minutes")
            elif isinstance(v, bool):
                v = int(v)
            salida[k] = v
        return salida

    def _deserializar(self, fila: sqlite3.Row) -> dict:
        d = dict(fila)
        d.pop("cliente_clave", None)
        for k in _CAMPOS_CIFRADOS:
            d[k] = self.proteccion.descifrar(d.get(k))
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
            "(destino, destino_clave, cuerpo, estado, intentos, ultimo_error, creado, actualizado) "
            "VALUES (?, ?, ?, 'pendiente', 1, ?, ?, ?)",
            (self.proteccion.cifrar(destino), self.proteccion.seudonimo(destino),
             self.proteccion.cifrar(cuerpo), error, ts, ts),
        )
        return cur.lastrowid

    def mensajes_pendientes(self, max_intentos: int) -> list[dict]:
        filas = self._ejecutar(
            "SELECT * FROM mensajes_salientes WHERE estado = 'pendiente' "
            "AND intentos < ? ORDER BY id",
            (max_intentos,),
        ).fetchall()
        return [self._mensaje(f) for f in filas]

    def mensajes_en_espera(self, destino: str) -> list[dict]:
        """Mensajes retenidos por la regla de 24 h, en orden, para un destino."""
        filas = self._ejecutar(
            "SELECT * FROM mensajes_salientes WHERE estado = 'esperando_ventana' AND destino_clave = ? "
            "ORDER BY id", (self.proteccion.seudonimo(destino),)).fetchall()
        return [self._mensaje(f) for f in filas]

    def mensajes_no_entregados(self, limite: int = 20) -> list[dict]:
        filas = self._ejecutar(
            "SELECT * FROM mensajes_salientes WHERE estado IN ('no_entregado', 'fallido') "
            "ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
        return [self._mensaje(f) for f in filas]

    def _mensaje(self, fila: sqlite3.Row) -> dict:
        m = dict(fila)
        m.pop("destino_clave", None)
        m["destino"] = self.proteccion.descifrar(m["destino"])
        m["cuerpo"] = self.proteccion.descifrar(m["cuerpo"])
        return m

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
