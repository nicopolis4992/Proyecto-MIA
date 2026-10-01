# Agente RAG — base de conocimiento

SCRUM-67 (embeddings e indexación), SCRUM-68 (recuperación), SCRUM-69
(respuesta fundamentada), SCRUM-70 (actualización).

## De dónde sale el conocimiento

| Fuente | Qué contiene | Quién la edita |
|---|---|---|
| `conocimiento/*.md` | Información del negocio, una sección `## ` por tema | Equipo (SCRUM-66/99), validado por la propietaria |
| `app/cotizacion/tarifario_v1.json` | Precios, recargos, zonas, restricción vehicular | Se edita solo el JSON (SCRUM-98) |

Los precios **no se escriben en los .md**: se generan desde el tarifario en cada
indexación. Así el RAG y el motor de cotización nunca dan valores distintos.

## Procedimiento para actualizar la base (SCRUM-70)

1. Editar el archivo correspondiente:
   - cambio de precio, recargo o zona → `app/cotizacion/tarifario_v1.json`
   - cambio de servicio, política o pregunta frecuente → `app/rag/conocimiento/*.md`
     (cada sección `## Título` debe entenderse sola, sin depender de otra).
2. Re-indexar y probar con una consulta:
   ```bash
   python -m app.rag.indexador --probar "cuánto cuesta el baño para un perro grande"
   ```
   Solo se recalculan los fragmentos cuyo texto cambió (se compara un hash);
   los eliminados se borran del índice. `--forzar` recalcula todo (necesario
   solo si se cambia el modelo o la dimensión de embeddings).
3. Versionar el cambio junto con `app/rag/indice_local.json` y desplegar.

Si se despliega sin re-indexar, el servidor sincroniza el índice al arrancar
(`crear_agente_rag`), así que nunca queda desactualizado; el paso 2 sirve para
verificar la respuesta antes de que la vea un cliente.

## Backends

- `RAG_BACKEND=local` (por defecto): `indice_local.json`, búsqueda exacta.
- `RAG_BACKEND=pgvector` + `SUPABASE_DB_URL`: tabla `rag_fragmentos` en Supabase.
  Crear la tabla con `esquema_pgvector.sql`. Implementado, **aún no probado**
  contra la instancia real.

## Parámetros

- `RAG_K` (4): fragmentos recuperados.
- `RAG_UMBRAL` (0.66): similitud mínima. Bajo ese valor no se llama al LLM y se
  responde "no tengo esa información", y se avisa a la propietaria. Calibrado
  con 12 consultas el 30-sep; recalibrar con el conjunto de evaluación de SCRUM-71.
