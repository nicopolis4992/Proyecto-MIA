"""Pruebas de la base de datos de Supabase contra PostgreSQL REAL.

Emula las condiciones de Supabase que importan para el esquema:
  * las migraciones las ejecuta un usuario SIN superusuario, con CREATEROLE,
    CREATEDB y BYPASSRLS (como el `postgres` de Supabase);
  * existen los roles de la API (anon, authenticated, service_role) y el
    esquema `extensions`.

Configuración (si no está, las pruebas se omiten):
    MIA_PG_ADMIN_DSN="host=... port=... user=postgres dbname=postgres"
El servidor debe ser un clúster propio para pruebas (se crean roles globales).
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

ADMIN_DSN = os.environ.get("MIA_PG_ADMIN_DSN")
if not ADMIN_DSN:
    pytest.skip("MIA_PG_ADMIN_DSN no definido: se omiten las pruebas de base de datos",
                allow_module_level=True)

import psycopg  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402

from mia_agenda import Cifrador, Seudonimizador  # noqa: E402

MIGRACIONES = RAIZ / "supabase" / "migrations"
PLANTILLA = "mia_plantilla_supabase"
USUARIO_MIGRACIONES = "supabase_postgres_sim"
ROLES_PRUEBA = {"agente": "mia_agente", "aprobacion": "mia_aprobacion",
                "sistema": "mia_sistema", "lectura": "mia_lectura"}
GYE = ZoneInfo("America/Guayaquil")


def _dsn(usuario: str = "postgres", dbname: str = "postgres") -> str:
    return ADMIN_DSN.replace("user=postgres", f"user={usuario}").replace("dbname=postgres", f"dbname={dbname}")


def _admin(dbname: str = "postgres") -> psycopg.Connection:
    return psycopg.connect(_dsn("postgres", dbname), autocommit=True)


def _eliminar_bd(conn: psycopg.Connection, nombre: str) -> None:
    conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (nombre,))
    conn.execute(f'DROP DATABASE IF EXISTS "{nombre}"')


@pytest.fixture(scope="session")
def plantilla():
    with _admin() as conn:
        for r in ("anon", "authenticated", "service_role"):
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (r,)).fetchone():
                conn.execute(f"CREATE ROLE {r} NOLOGIN")
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (USUARIO_MIGRACIONES,)).fetchone():
            conn.execute(f"CREATE ROLE {USUARIO_MIGRACIONES} LOGIN NOSUPERUSER CREATEROLE CREATEDB BYPASSRLS")
        if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (PLANTILLA,)).fetchone():
            conn.execute(f'ALTER DATABASE "{PLANTILLA}" IS_TEMPLATE false')
            _eliminar_bd(conn, PLANTILLA)
        conn.execute(f'CREATE DATABASE "{PLANTILLA}" OWNER {USUARIO_MIGRACIONES}')
    with _admin(PLANTILLA) as conn:
        # Supabase trae el esquema `extensions` creado de antemano.
        conn.execute("CREATE SCHEMA IF NOT EXISTS extensions")
        conn.execute(f"GRANT USAGE, CREATE ON SCHEMA extensions TO {USUARIO_MIGRACIONES}")
    # Las migraciones corren como el usuario NO superusuario, en orden.
    with psycopg.connect(_dsn(USUARIO_MIGRACIONES, PLANTILLA), autocommit=True) as conn:
        for script in sorted(MIGRACIONES.glob("*.sql")):
            conn.execute(script.read_text(encoding="utf-8"))
            conn.execute("RESET ROLE")
            conn.execute("RESET search_path")
    with _admin(PLANTILLA) as conn:
        for sufijo, rol in ROLES_PRUEBA.items():
            usuario = f"t_{sufijo}"
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (usuario,)).fetchone():
                conn.execute(f"CREATE ROLE {usuario} LOGIN IN ROLE {rol}")
        for usuario in ("t_anon", "t_authenticated"):
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (usuario,)).fetchone():
                conn.execute(f"CREATE ROLE {usuario} LOGIN IN ROLE {usuario[2:]}")
    yield PLANTILLA


@pytest.fixture
def bd(plantilla):
    """Base aislada por prueba. Devuelve una función conectar(rol)."""
    nombre = f"tsb_{uuid.uuid4().hex[:10]}"
    with _admin() as conn:
        conn.execute(f'CREATE DATABASE "{nombre}" TEMPLATE "{plantilla}"')
    abiertas: list[psycopg.Connection] = []

    def conectar(rol: str = "agente") -> psycopg.Connection:
        usuario = "postgres" if rol == "admin" else f"t_{rol}"
        c = psycopg.connect(_dsn(usuario, nombre), autocommit=True)
        abiertas.append(c)
        return c

    yield conectar
    for c in abiertas:
        c.close()
    with _admin() as conn:
        _eliminar_bd(conn, nombre)


@pytest.fixture(scope="session")
def claves():
    seud = Seudonimizador(b"clave-de-operacion-solo-para-pruebas-0123456789")
    cif = Cifrador([Fernet.generate_key()])
    return seud, cif


@pytest.fixture
def manana_10h():
    """Un horario futuro realista: pasado mañana a las 10:00 en Quito."""
    return (datetime.now(GYE) + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
