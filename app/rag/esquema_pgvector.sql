-- Base vectorial del Agente RAG en Supabase (SCRUM-67).
-- Ejecutar una vez en el SQL editor de Supabase. La dimension debe
-- coincidir con GEMINI_EMBED_DIM (768 por defecto).

create extension if not exists vector;

create table if not exists rag_fragmentos (
    id          text primary key,          -- ej. "negocio#vigencia_de_la_cotizacion"
    fuente      text not null,             -- archivo de origen
    titulo      text not null,
    texto       text not null,
    hash        text not null,             -- sha256 del texto, para re-indexado incremental
    embedding   vector(768) not null,
    actualizado timestamptz not null default now()
);

-- Con pocas decenas de filas la busqueda secuencial es exacta y suficiente.
-- Si la base crece a miles de fragmentos, agregar:
-- create index on rag_fragmentos using hnsw (embedding vector_cosine_ops);
