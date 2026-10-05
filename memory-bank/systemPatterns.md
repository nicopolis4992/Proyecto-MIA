# System Patterns - Proyecto MIA

## Arquitectura general
Orquestador multiagente en LangGraph, cliente-servidor, integrado con
WhatsApp Business Cloud API (directo, sin BSP intermediario).

## Flujo de un mensaje entrante
1. `main.py` (FastAPI): recibe el POST /webhook de Meta (texto o imagen),
   deduplica, y en segundo plano llama a
   `app/agents/orchestrator_graph.py::procesar_mensaje(remitente, texto, imagen, id_citado)`.
2. (`app/agent.py` se elimino el 05-oct: era un reexport de una linea.)
3. `orchestrator_graph.py`: construye/usa un grafo de LangGraph con:
   - Nodo `nlu` (siempre primero): llama a `nlu_extractor.py` para
     clasificar intencion + extraer entidades + confianza, vía salida
     estructurada (JSON schema) de Gemini.
   - `add_conditional_edges` enruta segun la intencion detectada:
     - `consultar` -> `agente_rag`
     - `agendar` -> `agente_agenda`
     - `general` (y fallback) -> `agente_general`
4. Nodos `agente_rag` y `agente_agenda` son **stubs** por ahora (esas
   historias, SCRUM-66 a 71 y agenda real, todavia no estan hechas). Se
   deben reemplazar por la implementacion real sin tocar el enrutamiento.
5. `agente_general` sí es real: reutiliza el comportamiento original de
   Gemini respondiendo libremente, para saludos/agradecimientos/fuera de
   alcance.

## Patron: doble intencion de import
`orchestrator_graph.py` importa `nlu_extractor` con try/except (relativo
si es parte del paquete `app.agents`, absoluto si se corre como script
suelto para pruebas manuales). Mantener este patron al agregar mas
modulos internos del paquete `agents/`.

## Patron: instancia unica de cliente/grafo
El cliente de Gemini y el grafo compilado se crean UNA VEZ a nivel de
modulo en `orchestrator_graph.py` (`_client`, `_grafo_compilado`), no en
cada request, para no reconstruir nada por cada mensaje entrante.

## Human-in-the-loop (decision de diseno central)
Ningun agente confirma una cita de forma autonoma. El agente de agenda
(pendiente de implementar) debe generar un resumen (mascota, servicio,
horario, cotizacion) y enviarlo a la propietaria por WhatsApp o correo
para aprobacion/rechazo antes de notificar al cliente. Alineado con
ISO/IEC 25059:2023 (controlabilidad por parte del usuario).

## Convenciones de documentacion (aplican tambien al codigo)
- No usar la palabra "alternativa" al referirse a los enfoques de solucion
  en documentos academicos (no aplica al codigo).
- No mencionar el "pico y placa" por su nombre en documentos formales,
  pero SI se debe implementar como restriccion parametrizable (no hardcode)
  en el motor de reglas del agente de agenda.
- Mantener a la propietaria anonimizada en cualquier documento o log que
  pueda ser publico.
