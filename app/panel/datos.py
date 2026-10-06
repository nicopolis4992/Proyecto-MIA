"""
Datos del panel web: indicadores para la propietaria y datos de ejemplo.

Indicadores elegidos por lo que el proyecto promete medir (SCRUM-95/96):
- tiempo desde la solicitud hasta la confirmacion de la cita;
- cuantas cotizaciones salen con precio exacto vs rango (variabilidad);
- ingresos estimados, servicios mas pedidos, modalidad, proximas citas.
"""

from __future__ import annotations

import random
from collections import Counter
from datetime import datetime, timedelta

from app.agenda import mensajes
from app.config import ZONA_HORARIA, ahora
from app.cotizacion.cotizador import Cotizador


def _cita_publica(c: dict) -> dict:
    cot = c.get("cotizacion") or {}
    inicio = datetime.fromisoformat(c["fecha_hora"]) if c.get("fecha_hora") else None
    duracion = cot.get("duracion_agenda_min", 60)
    return {
        "id": c["id"],
        "estado": c["estado"],
        "inicio": inicio.isoformat() if inicio else None,
        "fin": (inicio + timedelta(minutes=duracion)).isoformat() if inicio else None,
        "fecha_legible": mensajes.fecha_legible(inicio) if inicio else "sin fecha",
        "fecha_corta": (f"{mensajes.DIAS[inicio.weekday()][:3]} {inicio.day} "
                        f"{mensajes.MESES[inicio.month - 1][:3]} · {inicio.strftime('%H:%M')}") if inicio else "—",
        "cliente": c.get("cliente_nombre") or c["cliente_telefono"],
        "mascotas": [m.get("nombre") or "mascota" for m in c["mascotas"]],
        "descripcion": [mensajes._descripcion_mascota(m) for m in c["mascotas"]],
        "servicios": [m.get("servicio_nombre") for m in cot.get("mascotas", [])],
        "modalidad": c["modalidad"],
        "sector": c.get("sector"),
        "total": mensajes.texto_total(c),
        "total_rango": cot.get("total"),
        "comprometido": bool(cot.get("comprometido")) or c.get("total_acordado") is not None,
        "preguntas_pendientes": cot.get("preguntas_pendientes", []),
        "revision_manual": c.get("requiere_revision_manual", False),
        "ciclo_aprobacion": c.get("ciclo_aprobacion", 1),
    }


def _monto(c: dict) -> float:
    unico = mensajes.total_de(c)
    if unico is not None:
        return unico
    total = (c.get("cotizacion") or {}).get("total")
    return (total[0] + total[1]) / 2 if total else 0.0


def resumen(repo, desde: datetime | None = None) -> dict:
    citas = repo.todas_las_citas()
    hoy = ahora()
    confirmadas = [c for c in citas if c["estado"] == "confirmada"]
    pendientes = [c for c in citas if c["estado"] in ("pendiente_aprobacion", "propuesta_cliente", "en_reprogramacion")]

    # Tiempo de agendamiento: creacion de la cita -> confirmacion al cliente.
    tiempos = []
    for c in confirmadas:
        ev = {e["tipo"]: e["fecha"] for e in repo.eventos_de_cita(c["id"])}
        if "creada" in ev and "confirmada" in ev:
            delta = datetime.fromisoformat(ev["confirmada"]) - datetime.fromisoformat(ev["creada"])
            tiempos.append(delta.total_seconds() / 60)

    cotizadas = [c for c in citas if c.get("cotizacion")]
    exactas = [c for c in cotizadas if _cita_publica(c)["comprometido"]]
    amplitudes = [c["cotizacion"]["total"][1] - c["cotizacion"]["total"][0]
                  for c in cotizadas if c["cotizacion"].get("total")]

    servicios = Counter(s for c in citas if c["estado"] != "rechazada"
                        for s in _cita_publica(c)["servicios"] if s)
    tarifario = Cotizador().t  # el tamano tipico de la raza completa lo no declarado
    tamanos = Counter(m.get("tamano") or (tarifario.raza(m.get("raza")) or {}).get("tamano") or "sin dato"
                      for c in citas for m in c["mascotas"])

    dias = []
    for i in range(-14, 15):
        dia = (hoy + timedelta(days=i)).date()
        n = sum(1 for c in citas if c["estado"] in ("confirmada", "aprobada", "pendiente_aprobacion")
                and c.get("fecha_hora") and datetime.fromisoformat(c["fecha_hora"]).date() == dia)
        dias.append({"fecha": dia.isoformat(), "citas": n})

    proximas = sorted((c for c in citas if c["estado"] in ("confirmada", "aprobada")
                       and c.get("fecha_hora") and datetime.fromisoformat(c["fecha_hora"]) >= hoy),
                      key=lambda c: c["fecha_hora"])

    clientes = Counter(c["cliente_telefono"] for c in citas if c["estado"] == "confirmada")
    return {
        "generado": hoy.isoformat(timespec="minutes"),
        "kpis": {
            "citas_confirmadas": len(confirmadas),
            "ingresos_estimados": round(sum(_monto(c) for c in confirmadas), 2),
            "pendientes_aprobacion": len(pendientes),
            "tiempo_confirmacion_min": round(sum(tiempos) / len(tiempos), 1) if tiempos else None,
            "pct_precio_exacto": round(100 * len(exactas) / len(cotizadas)) if cotizadas else None,
            "amplitud_media_usd": round(sum(amplitudes) / len(amplitudes), 2) if amplitudes else None,
            "pct_puerta_a_puerta": round(100 * sum(1 for c in confirmadas if c["modalidad"] == "puerta_a_puerta")
                                         / len(confirmadas)) if confirmadas else None,
            "clientes_recurrentes": sum(1 for n in clientes.values() if n > 1),
            "rechazadas": sum(1 for c in citas if c["estado"] in ("rechazada", "cancelada")),
        },
        "citas_por_dia": dias,
        "servicios": [{"servicio": s, "citas": n} for s, n in servicios.most_common()],
        "tamanos": [{"tamano": mensajes.ETIQUETA_TAMANO.get(t, t), "mascotas": tamanos.get(t, 0)}
                    for t in ("pequeno", "mediano", "grande", "sin dato") if tamanos.get(t)],
        "proximas": [_cita_publica(c) for c in proximas[:10]],
        "pendientes": [_cita_publica(c) for c in pendientes],
        "citas": [_cita_publica(c) for c in citas],
    }


def detalle_cita(repo, cita_id: int) -> dict | None:
    c = repo.obtener_cita(cita_id)
    if not c:
        return None
    return {**_cita_publica(c), "cotizacion": c.get("cotizacion"), "eventos": repo.eventos_de_cita(cita_id),
            "mascotas_detalle": c["mascotas"]}


# ---------------------------------------------------------------------------
# Datos de ejemplo (SIMULADOS) para mostrar el panel antes del piloto
# ---------------------------------------------------------------------------

_EJEMPLOS = [
    ("Luna", "golden", "completo", "sin_motas"), ("Toby", "shih tzu", "completo", "moderado"),
    ("Kira", "schnauzer", "basico", "sin_motas"), ("Rocky", "husky", "deslanado", "sin_motas"),
    ("Mia", "mestizo", "express", "sin_motas"), ("Max", "pug", "premium", "sin_motas"),
    ("Coco", "poodle", "completo", "severo"), ("Nala", "labrador", "basico", "sin_motas"),
    ("Simba", "pomerania", "completo", "moderado"), ("Lola", "chihuahua", "express", "sin_motas"),
    ("Bruno", "pastor ingles", "completo", "sin_motas"), ("Canela", "mestizo", "basico", "moderado"),
]
_SECTORES = ["El Condado", "Cotocollao", "La Carolina", "Condado Alto"]


def cargar_ejemplo(repo, cotizador: Cotizador, n: int = 24, semilla: int = 42) -> int:
    """Crea citas SIMULADAS (telefonos 59399990xxxx) en las ultimas y proximas 2 semanas."""
    rng = random.Random(semilla)
    hoy = ahora().replace(minute=0, second=0, microsecond=0)
    creadas = 0
    for i in range(n):
        nombre, raza, servicio, estado_manto = rng.choice(_EJEMPLOS)
        tamano = rng.choice(["pequeno", "mediano", "grande"]) if raza in ("mestizo", "poodle") else None
        mascota = {"nombre": nombre, "raza": raza, "servicio": servicio, "estado": estado_manto,
                   "comportamiento": "tranquilo", **({"tamano": tamano} if tamano else {})}
        modalidad = rng.choice(["salon", "salon", "puerta_a_puerta"])
        sector = rng.choice(_SECTORES) if modalidad == "puerta_a_puerta" else None
        dia = hoy + timedelta(days=rng.randint(-14, 14))
        while dia.weekday() == 6:
            dia += timedelta(days=1)
        inicio = dia.replace(hour=rng.choice([9, 10, 11, 12, 14, 15]))
        cot = cotizador.cotizar([mascota], modalidad, sector)
        azar = rng.random()
        estado = ("confirmada" if inicio < hoy or azar < 0.7
                  else "pendiente_aprobacion" if azar < 0.9 else "rechazada")
        cid = repo.crear_cita(
            cliente_telefono=f"5939999{rng.randint(10000, 10011):05d}", cliente_nombre=None,
            mascotas=[mascota], fecha_hora=inicio.astimezone(ZONA_HORARIA), modalidad=modalidad,
            sector=sector, cotizacion=cot, estado=estado,
        )
        if estado == "confirmada":
            # Simula el tiempo real de aprobacion de la propietaria (5-90 min).
            repo.registrar_evento(cid, "aprobada", {"simulado": True})
            repo._ejecutar(
                "UPDATE eventos_cita SET fecha = ? WHERE cita_id = ? AND tipo = 'aprobada'",
                ((datetime.now(ZONA_HORARIA) + timedelta(minutes=rng.randint(5, 90))).isoformat(timespec="seconds"), cid),
            )
            repo._ejecutar(
                "INSERT INTO eventos_cita (cita_id, tipo, detalle, fecha) SELECT cita_id, 'confirmada', "
                "'{\"simulado\": true}', fecha FROM eventos_cita WHERE cita_id = ? AND tipo = 'aprobada'",
                (cid,),
            )
        creadas += 1
    return creadas
