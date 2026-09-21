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

## Que falta (S4, vence 4 oct)
- Agente RAG real: base de conocimiento, embeddings, indexacion
  vectorial, recuperacion, generacion fundamentada, evaluacion.
  (SCRUM-66 a 71 - Por hacer)
- Manejo de mensajes ambiguos o incompletos en el NLU. (SCRUM-62)
- Evaluacion formal del modelo de clasificacion de intencion. (SCRUM-64)
- Clasificador de imagen (tamano/pelaje) por transfer learning.
  (SCRUM-102)
- Manejo de fotos de baja confianza/calidad (fallback). (SCRUM-104)

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
- Los nodos `agente_rag` y `agente_agenda` en el orquestador son stubs;
  cualquier prueba end-to-end por WhatsApp hoy responde con placeholders
  para esas dos intenciones, no con datos reales del negocio ni agenda
  real.
