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
"""

from __future__ import annotations

from datetime import datetime

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
ETIQUETA_TAMANO = {"pequeno": "pequeño", "mediano": "mediano", "grande": "grande"}
ETIQUETA_PELAJE = {"corto": "corto", "largo": "largo", "rizado": "rizado", "doble_capa": "doble capa"}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_legible(valor: str | datetime | None) -> str:
    if not valor:
        return "fecha por definir"
    f = datetime.fromisoformat(valor) if isinstance(valor, str) else valor
    hora = f.strftime("%H:%M")
    return f"{DIAS[f.weekday()]} {f.day} de {MESES[f.month - 1]} a las {hora}"


def total_de(cita: dict) -> float | None:
    if cita.get("total_acordado") is not None:
        return float(cita["total_acordado"])
    c = cita.get("cotizacion") or {}
    return c.get("total_estimado")


def _nombres(cita: dict) -> str:
    nombres = [m.get("nombre") or "su mascota" for m in cita["mascotas"]]
    return nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1]


def resumen_para_propietaria(cita: dict) -> str:
    c = cita.get("cotizacion") or {}
    lineas = [f"🐾 Nueva cita #{cita['id']} por aprobar"
              + (f" (revisión {cita['ciclo_aprobacion']})" if cita.get("ciclo_aprobacion", 1) > 1 else "")]
    lineas.append(f"Cliente: {cita.get('cliente_nombre') or 'sin nombre'} ({cita['cliente_telefono']})")
    for m, d in zip(cita["mascotas"], c.get("detalle_por_mascota", [{}] * len(cita["mascotas"]))):
        tam = ETIQUETA_TAMANO.get(m.get("tamano"), "tamaño ?")
        pel = "pelaje " + ETIQUETA_PELAJE.get(m.get("pelaje"), "?")
        precio = f" — {d['subtotal']:.2f}$" if d.get("subtotal") is not None else ""
        lineas.append(f"• {m.get('nombre') or 'Mascota'}: {d.get('servicio', m.get('servicio'))} "
                      f"({tam}, {pel}){precio}")
    lineas.append(f"Horario: {fecha_legible(cita.get('fecha_hora'))}")
    if cita["modalidad"] == "puerta_a_puerta":
        transporte = sum(x["valor"] for x in c.get("cargos_por_visita", []))
        lineas.append(f"Puerta a puerta: sí ({transporte:.2f}$)"
                      + (f" — sector: {cita['sector']}" if cita.get("sector") else ""))
    else:
        lineas.append("Modalidad: en el salón")
    total = total_de(cita)
    if total is not None:
        r = c.get("rango_estimado") or {}
        if cita.get("total_acordado") is None and c.get("tipo_cotizacion") == "rango_estimado":
            lineas.append(f"Total estimado: {total:.2f}$ (rango {r['minimo']:.2f}–{r['maximo']:.2f}$)")
        else:
            lineas.append(f"Total: {total:.2f}$")
    if c.get("datos_faltantes"):
        lineas.append(f"Falta confirmar: {', '.join(c['datos_faltantes'])}")
    if cita.get("requiere_revision_manual"):
        lineas.append("⚠️ La foto no permitió estimar bien: revisa el precio.")
    lineas.append("\nResponde a ESTE mensaje: \"listo\" para aprobar, \"no\" para rechazar, "
                  "o dime el cambio (ej. \"a las 12 está bien\", \"cóbrale 20\").")
    return "\n".join(lineas)


def confirmacion_cliente(cita: dict) -> str:
    """SCRUM-78: datos definitivos de la cita, con tono cercano."""
    partes = [f"¡Listo! 🐶 Queda agendado {_nombres(cita)} para el {fecha_legible(cita['fecha_hora'])}."]
    c = cita.get("cotizacion") or {}
    servicios = [d["servicio"] for d in c.get("detalle_por_mascota", [])]
    if len(servicios) == 1:
        partes.append(f"Servicio: {servicios[0].lower()}.")
    elif servicios:
        partes.append("Servicios: " + "; ".join(
            f"{m.get('nombre') or 'mascota'}: {s.lower()}" for m, s in zip(cita["mascotas"], servicios)) + ".")
    total = total_de(cita)
    if total is not None:
        if cita["modalidad"] == "puerta_a_puerta":
            partes.append(f"Total: {total:.2f}$ con el servicio puerta a puerta incluido.")
        else:
            partes.append(f"Total: {total:.2f}$.")
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
