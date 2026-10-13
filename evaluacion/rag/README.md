# SCRUM-71 — Evaluación del agente RAG

1. **Escribir las preguntas** (Daniel Loza) en `evaluacion/rag/preguntas.csv`, con el formato de
   [`preguntas_plantilla.csv`](preguntas_plantilla.csv):
   - ~40 que la base **sabe** (`debe_declinar = no`), con los datos clave esperados separados por `;`
     y la categoría del fragmento que debería recuperarse (si vale más de una: `politicas|faq`);
   - ~20 que **no sabe** (`debe_declinar = si`): ver la sección 4 de `app/rag/ESQUEMA_CONTENIDO.md`
     y temas ajenos al negocio.

   Escribirlas como un cliente (sin tildes, con errores) y **sin mirar los documentos**, para no
   copiar su redacción.
2. **Correr la evaluación**:
   ```
   python -m evaluacion.rag.evaluar_rag --preguntas evaluacion/rag/preguntas.csv               # solo recuperación (centavos)
   python -m evaluacion.rag.evaluar_rag --preguntas evaluacion/rag/preguntas.csv --respuestas  # + respuestas
   ```
   Las llamadas quedan grabadas en `grabaciones/`: con `--solo-lectura` se repite gratis.
3. **Resultados** en `resultados/rag_eval.md`:
   - recuperación hit@1 / hit@4;
   - exactitud;
   - "no sé" correcto y alucinación;
   - curva del umbral de similitud, con un umbral propuesto (hoy `RAG_UMBRAL=0.66`).

   El umbral propuesto se calcula con el mismo conjunto: antes de fijarlo, confirmarlo con unas preguntas nuevas.
