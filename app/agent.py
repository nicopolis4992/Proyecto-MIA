"""
Punto de entrada de agentes usado por main.py.

Version anterior (SCRUM-85): llamaba directo a Gemini, un solo nodo sin
enrutamiento.

Version actual (SCRUM-65): delega en el orquestador multiagente, que
clasifica la intencion del mensaje (SCRUM-60), extrae entidades (SCRUM-61)
y enruta a agente_rag / agente_agenda / agente_general segun corresponda.

main.py no necesita cambiar: sigue llamando a get_reply(texto) exactamente
igual que antes.
"""

from app.agents.orchestrator_graph import get_reply  # noqa: F401
