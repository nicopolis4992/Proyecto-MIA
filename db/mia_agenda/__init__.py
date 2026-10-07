"""Proyecto MIA · Agente de Agenda — persistencia de la cita propuesta (SCRUM-74)."""
from .registro import (
    Cotizacion, Descuento, Linea, Mascota, PropuestaCita, PropuestaInvalida,
    ResultadoRegistro, Tercero, construir_payload, obtener_resumen, registrar_cita_propuesta,
)
from .seguridad import Cifrador, ErrorConfiguracion, Seudonimizador, desde_entorno, normalizar_telefono

__all__ = [
    "Cotizacion", "Descuento", "Linea", "Mascota", "PropuestaCita", "PropuestaInvalida",
    "ResultadoRegistro", "Tercero", "construir_payload", "obtener_resumen", "registrar_cita_propuesta",
    "Cifrador", "ErrorConfiguracion", "Seudonimizador", "desde_entorno", "normalizar_telefono",
]
