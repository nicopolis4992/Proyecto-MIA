"""
Redaccion de los mensajes del flujo de agenda.

- resumen_para_propietaria: version minima de SCRUM-75 (Daniel Ocampo, en
  curso) para poder cerrar el ciclo de SCRUM-77/78 en el prototipo. Cuando
  SCRUM-75 este listo, reemplazar esta funcion por la suya conservando la
  firma (recibe la cita, devuelve texto).
- confirmacion_cliente / reprogramacion_cliente: SCRUM-78.

Los mensajes se arman con plantillas, no con el LLM: contienen montos y
horarios que no pueden variar. El tono replica el estilo de la propietaria
("Listo entonces manana a la 1 pm le agendo...").

La cotizacion guardada en la cita es la salida de Cotizador.cotizar
(tarifario v2): rangos [min, max] por mascota, traslado y total.
"""

from __future__ import annotations

from datetime import datetime

from app.cotizacion.cotizador import texto_rango

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
ETIQUETA_TAMANO = {"pequeno": "pequeño", "mediano": "mediano", "grande": "grande"}
ETIQUETA_GRUPO = {"A_maquina": "pelo de máquina", "B_deslanado": "doble capa",
                  "C_cepillado": "pelo de cepillado", "D_corto": "pelo corto"}
ETIQUETA_PREGUNTA = {"tamano": "tamaño", "raza_o_grupo_manto": "tipo de pelo",
                     "estado_manto": "nudos", "comportamiento": "comportamiento"}


def fecha_legible(valor: str | datetime | None) -> str:
    if not valor:
        return "fecha por definir"
    f = datetime.fromisoformat(valor) if isinstance(valor, str) else valor
    return f"{DIAS[f.weekday()]} {f.day} de {MESES[f.month - 1]} a las {f.strftime('%H:%M')}"


def total_de(cita: dict) -> float | None:
    """Monto unico de la cita, si existe (acordado o precio comprometido)."""
    if cita.get("total_acordado") is not None:
        return float(cita["total_acordado"])
    total = (cita.get("cotizacion") or {}).get("total")
    if total and total[0] == total[1]:
        return float(total[0])
    return None


def texto_total(cita: dict) -> str:
    unico = total_de(cita)
    if unico is not None:
        return f"{unico:.2f}$"
    total = (cita.get("cotizacion") or {}).get("total")
    return f"entre {total[0]:.2f}$ y {total[1]:.2f}$" if total else "por confirmar"


def _nombres(cita: dict) -> str:
    nombres = [m.get("nombre") or "su mascota" for m in cita["mascotas"]]
    return nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1]


_tarifario = None


def _raza_legible(raza: str | None) -> str | None:
    """La raza tal como la entiende el motor ("shitsu" -> "shih tzu")."""
    global _tarifario
    if not raza:
        return None
    if _tarifario is None:
        from app.cotizacion.cotizador import Cotizador
        _tarifario = Cotizador().t
    resueltas, _ = _tarifario.resolver_razas(raza)
    claves = [c for c, _ in resueltas if c]
    return " x ".join(claves) if claves and len(claves) == len(resueltas) else raza


def _descripcion_mascota(m: dict) -> str:
    rasgos = [_raza_legible(m.get("raza")), ETIQUETA_TAMANO.get(m.get("tamano")), ETIQUETA_GRUPO.get(m.get("grupo"))]
    return ", ".join(r for r in rasgos if r) or "sin datos"


def resumen_para_propietaria(cita: dict) -> str:
    c = cita.get("cotizacion") or {}
    ciclo = cita.get("ciclo_aprobacion", 1)
    lineas = [f"🐾 Nueva cita #{cita['id']} por aprobar" + (f" (revisión {ciclo})" if ciclo > 1 else "")]
    lineas.append(f"Cliente: {cita.get('cliente_nombre') or 'sin nombre'} ({cita['cliente_telefono']})")
    detalle = c.get("mascotas") or [{}] * len(cita["mascotas"])
    for m, d in zip(cita["mascotas"], detalle):
        precio = f" — {texto_rango(d['rango'])}" if d.get("rango") else ""
        lineas.append(f"• {m.get('nombre') or 'Mascota'}: {d.get('servicio_nombre', m.get('servicio'))} "
                      f"({_descripcion_mascota(m)}){precio}")
    lineas.append(f"Horario: {fecha_legible(cita.get('fecha_hora'))}")
    if cita["modalidad"] == "puerta_a_puerta":
        tr = c.get("traslado") or {}
        costo = texto_rango(tr.get("rango")) if tr.get("resuelto") else "POR DEFINIR (sector fuera de zonas)"
        lineas.append(f"Puerta a puerta: sí — {costo}" + (f" — sector: {cita['sector']}" if cita.get("sector") else ""))
    else:
        lineas.append("Modalidad: en el salón")
    lineas.append(f"Total: {texto_total(cita)}")
    if c.get("preguntas_pendientes"):
        lineas.append("Falta confirmar: " + ", ".join(ETIQUETA_PREGUNTA.get(p, p) for p in c["preguntas_pendientes"]))
    avisos = [a for m in c.get("mascotas", []) for a in m.get("avisos", [])] + \
             [a for a in c.get("avisos", []) if not a.startswith("iva_pendiente")]
    for a in avisos:
        lineas.append(f"ℹ️ {a}")
    if cita.get("requiere_revision_manual"):
        lineas.append("⚠️ La foto no permitió estimar bien: revisa el precio.")
    lineas.append("\nResponde a ESTE mensaje: \"listo\" para aprobar, \"no\" para rechazar, "
                  "o dime el cambio (ej. \"a las 12 está bien\", \"cóbrale 20\").")
    return "\n".join(lineas)


def confirmacion_cliente(cita: dict) -> str:
    """SCRUM-78: datos definitivos de la cita, con tono cercano."""
    partes = [f"¡Listo! 🐶 Queda agendado {_nombres(cita)} para el {fecha_legible(cita['fecha_hora'])}."]
    detalle = (cita.get("cotizacion") or {}).get("mascotas", [])
    servicios = [d.get("servicio_nombre") for d in detalle if d.get("servicio_nombre")]
    if len(servicios) == 1:
        partes.append(f"Servicio: {servicios[0]}.")
    elif servicios:
        partes.append("Servicios: " + "; ".join(
            f"{m.get('nombre') or 'mascota'}: {s}" for m, s in zip(cita["mascotas"], servicios)) + ".")
    total = texto_total(cita)
    if total != "por confirmar":
        incluye = " con el servicio puerta a puerta incluido" if cita["modalidad"] == "puerta_a_puerta" else ""
        partes.append(f"Total: {total}{incluye}.")
        if total_de(cita) is None:
            partes.append("El valor exacto se confirma al recibirlo, según el estado del pelo.")
    if cita["modalidad"] == "puerta_a_puerta":
        partes.append("Por favor, que alguien esté pendiente en casa a esa hora para entregar a su perrito.")
    partes.append("¡Gracias por confiar en nosotros!")
    return " ".join(partes)


def reprogramacion_cliente(cita: dict, alternativas: list[datetime], motivo: str | None = None) -> str:
    """SCRUM-78, camino de rechazo: ofrecer horarios ya validados."""
    inicio = "Disculpe, no vamos a poder atenderle el " + fecha_legible(cita.get("fecha_hora"))
    inicio += f" ({motivo})." if motivo else "."
    if not alternativas:
        return inicio + " ¿Qué otro día y hora le quedaría bien?"
    opciones = "\n".join(f"{i}. {fecha_legible(a)}" for i, a in enumerate(alternativas, 1))
    return (f"{inicio} Le puedo ofrecer estos horarios:\n{opciones}\n"
            "Respóndame con el número de la opción o indíqueme otro horario.")
