# Tech Context - Proyecto MIA

## Stack (finalizado por costo/simplicidad)
- **Orquestacion**: LangChain / LangGraph.
- **LLM**: Gemini 3.5 Flash-Lite (antes Gemini 2.5 Flash-Lite, deprecado
  por Google). SDK: `google-genai` (el paquete viejo
  `google-generativeai` esta deprecado, no usarlo).
- **Base de datos**: Supabase (Postgres + pgvector) para datos
  relacionales Y vectoriales en un solo servicio.
- **WhatsApp**: Meta WhatsApp Cloud API, integracion directa, sin BSP
  intermediario.
- **Hosting backend**: Railway.
- **Calendario**: Google Calendar API.
- **Vision artificial**: Google Colab (tier gratuito) para el
  entrenamiento por transfer learning del clasificador CNN (tamano/pelaje
  de la mascota).
- **Web framework**: FastAPI (main.py).

## Estructura de carpetas (repo)
```
Proyecto MIA/
  venv/
  app/
    main.py              # FastAPI: webhook GET/POST, healthcheck
    agent.py             # Delega en agents/orchestrator_graph.py
    whatsapp_client.py    # Envio de mensajes salientes (SCRUM-84)
    agents/
      __init__.py
      nlu_extractor.py    # Clasificacion de intencion + extraccion de entidades
      orchestrator_graph.py  # Grafo LangGraph con enrutamiento condicional
  requirements.txt
  .env                    # GEMINI_API_KEY, WHATSAPP_VERIFY_TOKEN, etc.
```

## Variables de entorno requeridas
- `GEMINI_API_KEY`
- `WHATSAPP_VERIFY_TOKEN` (token propio, no lo da Meta, se registra en
  Meta for Developers)

## Herramientas de documentacion (para entregables academicos, no codigo)
Python/PyMuPDF, libreria `docx` (Node.js), `merge_runs.py`, `validate.py`,
`soffice.py`, `pdftoppm`, LibreOffice.

## Gestion de proyecto
Jira, site `nicopolis4991.atlassian.net`, proyecto `SCRUM` (Team-managed).
Nota: Team-managed projects NO soportan import CSV jerarquico
(Epic Link/Parent deprecado); las relaciones Epic-Story y assignees se
configuran manualmente despues de importar.

## Calidad
Estandar de evaluacion: ISO/IEC 25059:2023 (modelo de calidad para
sistemas de IA), usado en la matriz comparativa de alternativas y como
marco de evaluacion general del sistema.
