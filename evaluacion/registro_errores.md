# Registro de errores y casos límite (SCRUM-91)

Errores encontrados durante el desarrollo y las pruebas del prototipo, con su
causa, la corrección aplicada y la prueba que evita que vuelva a aparecer.
Insumo para el capítulo de resultados y limitaciones (SCRUM-90). Versión 1.0 ·
11-oct-2026.

**Cómo se detectaron:**
- **Manual:** conversaciones de prueba del equipo (capturas del 30-sep al 06-oct).
- **Evaluación:** conjunto ciego de 222 mensajes (SCRUM-64).
- **Grabación:** errores que aparecieron al grabar los escenarios repetibles (`scripts/escenarios.py`).

Estado: **corregido** (con prueba automática), **mitigado** (reducido, sin
eliminar) o **abierto** (limitación conocida).

## 1. Comprensión del mensaje (NLU)

| ID | Caso | Detección | Causa | Corrección | Estado |
|---|---|---|---|---|---|
| E-01 | "Que la recojan en mi casa" se trataba como pregunta y salía de la reserva | Grabación | La regla de pregunta contaba "que" sin tilde como interrogativo | `parece_pregunta` solo acepta interrogativos inequívocos (con tilde o "?") · `02d6a68` | Corregido |
| E-02 | Una pregunta general en medio de una reserva ("¿tienen parqueadero?") se perdía | Manual | El atajo que omite el NLU dentro de una reserva enviaba todo a la agenda | La pregunta pasa por el NLU; la reserva se mantiene · `02d6a68` | Corregido |
| E-03 | Preguntas sobre el servicio clasificadas como *general* ("¿cuánto se demora?", "¿me puedo quedar?", "¿el precio puede cambiar?") | Evaluación (5 de 68) | Límite difuso entre *consultar* y *general* en la guía de anotación | Prompt v2 alineado a la guía; el RAG responde igual en ambos casos | Mitigado |
| E-04 | Preguntas sobre una cita existente clasificadas como *general* ("¿a qué hora tengo el turno?", "voy a llegar tarde") | Evaluación (2 de 85) | El prompt no cubre consultas sobre una cita ya agendada | La agenda reconoce la cita vigente del cliente cuando hay una | Mitigado |
| E-05 | La confianza que declara Gemini no separa aciertos de errores (0.96 frente a 0.94) | Evaluación | Los LLM no están calibrados en la confianza que declaran | No se usa como umbral; la ambigüedad se maneja con preguntas de seguimiento y relevo a la propietaria | Abierto |

Detalle de los 9 errores del conjunto ciego: `evaluacion/nlu/resultados/nlu_v2_entrenamiento.md`.

## 2. Agenda y aprobación

| ID | Caso | Detección | Causa | Corrección | Estado |
|---|---|---|---|---|---|
| E-06 | La propietaria cambiaba la hora y la cita se confirmaba sin preguntarle al cliente | Manual | La modificación se trataba como aprobación | Nuevo estado `propuesta_cliente`: el cliente acepta o elige otro horario · `7208b56` | Corregido |
| E-07 | "A esa hora no puedo" iniciaba una reserva nueva | Manual | No existía el camino de reprogramar | Estado `en_reprogramacion` y cancelación · `7208b56` | Corregido |
| E-08 | La sesión se cerraba tras confirmar y el cliente no podía cambiar su cita | Manual | La sesión se vaciaba al confirmar | La sesión recuerda la `cita_activa` · `7208b56` | Corregido |
| E-09 | El bot inventaba una hora cuando el cliente solo daba el día ("¿el lunes está bien?") | Manual | El extractor completaba la hora | `dia_consultado`: se ofrecen horarios de ese día · `7208b56` | Corregido |
| E-10 | Solo se ofrecían horarios de la mañana ("solo me dijiste hasta las 11") | Manual | Las alternativas eran los primeros huecos libres | Horarios repartidos en el día, `franja_preferida` y `hora_minima` · `b49d370` | Corregido |
| E-11 | Mensajes repetidos al cliente en algunos flujos | Grabación | Dos nodos respondían el mismo texto | Deduplicación `_mismo_texto` · `69434ed` | Corregido |
| E-12 | La propietaria no podía responder preguntas que el bot no sabía | Manual | No había canal de vuelta | Relevo de consultas: se le reenvía la pregunta y su respuesta llega al cliente · `7208b56` | Corregido |
| E-13 | Solicitudes sin respuesta de la propietaria quedaban abiertas indefinidamente | Análisis | No había seguimiento | Recordatorios, aviso al cliente y vencimiento (SCRUM-76) · `c6a9208` | Corregido |

## 3. Cotización

| ID | Caso | Detección | Causa | Corrección | Estado |
|---|---|---|---|---|---|
| E-14 | La cotización por foto mostraba solo dos servicios | Manual | Lista fija en el mensaje | Catálogo completo según el tipo de pelo · `ef4cb2d` | Corregido |
| E-15 | Un pedido fuera de catálogo ("sin el baño medicado") no tenía flujo y llegaba al RAG | Manual | No existía el concepto | `pedido_especial`: se anota y la propietaria define el precio; no se menciona el precio salvo que el cliente lo pregunte · `ef4cb2d`, `a604a2f` | Corregido |
| E-16 | Razas mal escritas o mestizas no se cotizaban | Manual | Búsqueda exacta de la raza | Alias, coincidencia aproximada y cruces de razas · `9c6675d` | Corregido |
| E-17 | No se medía cuánto se desvía la cotización de lo cobrado | Análisis | No se registraba el cobro real | Comando "cobré X a la cita #N" y métrica en el panel (SCRUM-95) · `9a6b666` | Corregido |
| E-18 | Clases raras del dataset de imágenes (grande, doble capa, muy enredado) con pocos ejemplos | Etiquetado | Distribución real del negocio | Partición agrupada por mascota; F1 por clase en SCRUM-105 | Abierto |

## 4. Base de conocimiento (RAG)

| ID | Caso | Detección | Causa | Corrección | Estado |
|---|---|---|---|---|---|
| E-19 | "¿Atienden gatos?" se respondía con un fragmento parecido ("no atendemos perros agresivos") | Manual | La similitud superaba el umbral sin responder la pregunta | El LLM devuelve `SIN_CONTEXTO` y la pregunta se releva a la propietaria · `69434ed` | Corregido |
| E-20 | Riesgo de que el bot conteste un precio u horario distinto del que usa para cotizar y agendar | Análisis | Datos copiados a mano en los documentos | Precios y horario se generan desde el tarifario y la configuración de la agenda · `69434ed` | Corregido |
| E-21 | Umbral de similitud (0.66) calibrado con solo 12 consultas | Análisis | No existía un set de evaluación | Recalibrar con SCRUM-71 | Abierto |

## 5. WhatsApp e infraestructura

| ID | Caso | Detección | Causa | Corrección | Estado |
|---|---|---|---|---|---|
| E-22 | Meta reintenta el webhook y el mensaje se procesaba dos veces | Análisis | Entrega "al menos una vez" | Deduplicación por id de mensaje · `e3b2d47` | Corregido |
| E-23 | Mensajes perdidos ante caídas de la API | Prueba simulada | Sin reintentos | Reintentos y cola persistente (SCRUM-87) · `e3b2d47` | Corregido |
| E-24 | Regla de 24 h: Meta rechaza los mensajes que inicia el bot fuera de esa ventana (131047) | Documentación de Meta | Política de WhatsApp | Se marca como no entregado y se le pide a la propietaria escribir al cliente · `fb81645`. En producción hacen falta plantillas aprobadas por Meta | Mitigado |
| E-25 | Número fuera de la lista del número de prueba (131030) y token vencido (190) | Pruebas | Configuración de Meta | Mensaje explicativo y diagnóstico en el panel · `fb81645` | Corregido |
| E-26 | Si WhatsApp no le llega a la propietaria, la solicitud se pierde | Análisis | Un solo canal | Respaldo por correo (SCRUM-86) · `c6a9208` | Corregido |
| E-27 | Un escenario grabado ocultaba errores detrás del mensaje de "error técnico" | Grabación | La prueba solo revisaba que hubiera respuesta | Las pruebas fallan si aparece el mensaje de error técnico · `a604a2f` | Corregido |

## 6. Resumen

| Componente | Corregidos | Mitigados | Abiertos |
|---|---|---|---|
| NLU | 2 | 2 | 1 |
| Agenda y aprobación | 8 | 0 | 0 |
| Cotización | 4 | 0 | 1 |
| RAG | 2 | 0 | 1 |
| WhatsApp e infraestructura | 5 | 1 | 0 |
| **Total** | **21** | **3** | **3** |

**Limitaciones abiertas que conviene declarar en el informe:**
- La confianza que declara el LLM no sirve como umbral (E-05).
- Hay pocos ejemplos de las clases raras de imagen (E-18).
- El umbral del RAG no se ha evaluado con un set formal (E-21).
- Para producción hacen falta plantillas de Meta para los mensajes que inicia el bot (E-24).
