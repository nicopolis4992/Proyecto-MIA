# Active Context - Proyecto MIA

Ultima actualizacion: Sprint S4 - Desarrollo II (21 sep - 4 oct 2026)

## En que estamos trabajando ahora mismo
Sprint S4 recien empezado. Se acaba de completar y probar end-to-end la
integracion del agente NLU con el orquestador multiagente:

- SCRUM-60 (Clasificar intencion del mensaje): HECHO. Probado con 3
  mensajes de ejemplo (agendar/consultar/general), clasificacion correcta
  con confianza 0.98-1.00, con log de trazabilidad.
- SCRUM-61 (Extraer entidades relevantes): HECHO. Extrae servicio
  mencionado, fecha/hora relativa y tipo de mascota en el mismo llamado
  que la clasificacion de intencion (una sola llamada a Gemini con
  salida estructurada, no dos llamadas separadas).
- SCRUM-65 (Integrar el agente NLU con el orquestador): HECHO. El
  orquestador ahora enruta con `add_conditional_edges` en vez del nodo
  unico anterior. Nodos `agente_rag` y `agente_agenda` son stubs
  temporales (todavia no implementados). `agente_general` es real.
- (historico) `app/agent.py` delegaba en
  `app/agents/orchestrator_graph.py::get_reply` (eliminado el 05-oct), sin necesidad de tocar
  `main.py`.

## Cambio de sprint reciente
SCRUM-65 y SCRUM-61 estaban originalmente etiquetadas S3 (vencio 20 sep)
pero dependian de SCRUM-60 que ya estaba en S4. Se movieron ambas a S4
para alinear con su dependencia real.

## Actualizacion 30 sep
Prototipo integrado de punta a punta (ver progress.md). El orquestador ahora
tiene entradas directas para la propietaria (aprobacion) y para fotos
(cotizacion), y `procesar_mensaje(remitente, texto, imagen, id_citado)`
reemplaza a `get_reply(texto)` en main.py (get_reply se mantiene por
compatibilidad). Dependencias de agentes se construyen perezosamente en el
primer mensaje (`crear_dependencias`), inyectables para pruebas/simulador.

## Siguiente foco (anterior al 30 sep)
1. Implementar el Agente RAG real (SCRUM-66 a 71): construir base de
   conocimiento del negocio, generar embeddings, indexar en pgvector,
   recuperar contexto, generar respuesta fundamentada, evaluar calidad.
   Esto reemplaza el `nodo_rag_stub` en `orchestrator_graph.py`.
2. Agente de Cotizacion por Imagen (SCRUM-102, 104): entrenar el
   clasificador CNN por transfer learning en Colab, manejar fotos de baja
   confianza.
3. Agente de Agenda real (a cargo de Daniel Fernando): integracion con
   Google Calendar, motor de reglas de restricciones operativas. Esto
   reemplaza `nodo_agenda_stub`.

## Decisiones abiertas / pendientes
- Aun no se ha definido el formato exacto del log de trazabilidad del
  NLU en produccion (hoy solo va a stdout via `logging`; deberia
  persistirse en Supabase para poder evaluar el modelo despues, ver
  SCRUM-64).
