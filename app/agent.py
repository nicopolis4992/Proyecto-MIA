"""
Punto de entrada de agentes usado por main.py.

Version SCRUM-85: llamaba directo a Gemini, un solo nodo sin enrutamiento.
Version SCRUM-65: delegaba en el orquestador con NLU (texto -> texto).
Version actual (prototipo S4): `procesar_mensaje` recibe tambien el
remitente (para la sesion y para distinguir a la propietaria), la imagen si
la hay y el id del mensaje citado (respuestas de aprobacion).
"""

from app.agents.orchestrator_graph import get_reply, procesar_mensaje  # noqa: F401
