# Progress - Proyecto MIA

## Que funciona (probado)
- Webhook de WhatsApp Cloud API: recepcion (GET verify + POST) y envio de
  mensajes salientes. (SCRUM-83, 84 - Finalizado)
- Orquestador base en LangGraph desplegado end-to-end (demo hecha).
  (SCRUM-85 - Finalizado, ahora superado por el enrutamiento condicional)
- Clasificacion de intencion (agendar / consultar / general) con
  confianza y log de trazabilidad. (SCRUM-60 - Hecho)
- Extraccion de entidades (servicio, fecha/hora relativa, tipo de
  mascota) en la misma llamada que la clasificacion. (SCRUM-61 - Hecho)
- Enrutamiento condicional del orquestador segun intencion, con stubs
  para RAG y Agenda. (SCRUM-65 - Hecho)

## Prototipo integrado (30 sep, Nico) - probado con simulador.py
- Agente RAG real (SCRUM-67/68/69/70): app/rag/. Indice local JSON con
  gemini-embedding-001 @768, umbral 0.66, re-indexado incremental por hash.
  Precios generados desde el tarifario. pgvector implementado sin probar.
- Cotizacion por foto (SCRUM-103/104): app/cotizacion/cotizador_imagen.py +
  app/vision/. Backend provisional Gemini zero-shot; CNN ONNX lista para
  enchufar. Script de entrenamiento Colab (SCRUM-102) en entrenamiento/.
- Aprobacion de la propietaria y confirmacion al cliente (SCRUM-77/78):
  app/agenda/aprobacion.py (aprobar / rechazar / modificar y reproponer).
- Agente de agenda conversacional (reemplaza el stub) con validacion de
  horario + restriccion vehicular y alternativas: app/agenda/.
- SCRUM-87: reintentos con backoff + cola de salida persistente + dedupe de
  webhooks + procesamiento en segundo plano.
- Persistencia provisional SQLite (app/persistencia/) hasta SCRUM-74.
- `python simulador.py --guion` corre la demo completa sin Meta.

## Que falta (S4, vence 4 oct)
- Contenido validado de la base de conocimiento (SCRUM-66/99) y evaluacion
  del RAG (SCRUM-71). Hoy hay un borrador provisional en app/rag/conocimiento/.
- Manejo de mensajes ambiguos o incompletos en el NLU. (SCRUM-62)
- Evaluacion formal del modelo de clasificacion de intencion. (SCRUM-64)
- Entrenar la CNN en Colab (SCRUM-102): bloqueado por fotos propias y
  manifiesto real de SCRUM-101.

## Que falta (S5 en adelante)
- Agente de Agenda real: integracion Google Calendar, motor de reglas
  de restricciones operativas, flujo de aprobacion humana con la
  propietaria.
- Persistencia en base de datos relacional (Supabase): conversaciones,
  cotizaciones, decisiones de aprobacion, citas confirmadas.
- Piloto con clientes reales (4 semanas minimo).

## Limitaciones conocidas / riesgos activos
- El clasificador de imagen se entrena principalmente con Stanford Dogs
  Dataset + fotos propias limitadas (la propietaria no las conserva de
  forma sistematica). Precision esperada menor en mestizos o razas poco
  representadas.
- El registro de Excel del negocio solo tiene datos del ano en curso: no
  hay serie historica suficiente para modelado predictivo de demanda a
  largo plazo.
- Disponibilidad real (Google Calendar, SCRUM-72) no integrada: solo se
  valida horario laboral provisional y choques con citas en la base local.
- Desajuste de vocabulario/factores de pelaje entre datasets/imagenes/src/
  clases.py (doble 1.15, largo 1.20) y tarifario_v1.json (doble_capa 1.25,
  largo 1.15). El clasificador traduce doble->doble_capa; los factores los
  decide el tarifario. Pendiente alinear con Daniel Loza.
