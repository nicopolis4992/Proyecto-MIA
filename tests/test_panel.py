"""Panel web: dashboard de la propietaria y datos de ejemplo (sin LLM)."""

from fastapi.testclient import TestClient

from app.cotizacion.cotizador import Cotizador
from app.main import app
from app.panel import datos, rutas
from app.persistencia.repositorio import Repositorio


def test_dashboard_con_datos_de_ejemplo():
    repo = Repositorio(":memory:")
    assert datos.cargar_ejemplo(repo, Cotizador(), n=20) == 20
    r = datos.resumen(repo)
    k = r["kpis"]
    assert k["citas_confirmadas"] + k["pendientes_aprobacion"] + k["rechazadas"] == 20
    assert k["ingresos_estimados"] > 0 and k["tiempo_confirmacion_min"] > 0
    assert 0 <= k["pct_precio_exacto"] <= 100
    assert len(r["citas_por_dia"]) == 29 and r["servicios"]
    detalle = datos.detalle_cita(repo, r["citas"][0]["id"])
    assert detalle["eventos"][0]["tipo"] == "creada"


def test_panel_exige_clave_si_esta_configurada(monkeypatch, tmp_path):
    monkeypatch.setattr(rutas, "RUTA_DB_DEMO", tmp_path / "demo.sqlite3")
    monkeypatch.setattr(rutas, "_demo", None)
    monkeypatch.setenv("DEMO_CLAVE", "secreta")
    cliente = TestClient(app)
    assert cliente.get("/panel/api/dashboard").status_code == 401
    assert cliente.get("/panel/api/dashboard", headers={"X-Panel-Clave": "secreta"}).status_code == 200
    assert cliente.get("/panel?clave=secreta").status_code == 200


def test_resumen_muestra_la_raza_corregida():
    from app.agenda.mensajes import _descripcion_mascota
    assert _descripcion_mascota({"raza": "shitsu", "tamano": "pequeno"}) == "shih tzu, pequeño"
    assert _descripcion_mascota({"raza": "schnauzer con poodle"}) == "schnauzer x poodle"


def test_base_antigua_se_migra_con_la_columna_de_pedido_especial(tmp_path):
    import sqlite3

    ruta = tmp_path / "vieja.sqlite3"
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE citas (id INTEGER PRIMARY KEY, cliente_telefono TEXT, mascotas TEXT, "
                "modalidad TEXT, estado TEXT, fecha_registro TEXT, actualizada TEXT)")
    con.commit(); con.close()
    repo = Repositorio(ruta)
    columnas = {f[1] for f in repo._con.execute("PRAGMA table_info(citas)")}
    assert "pedido_especial" in columnas
