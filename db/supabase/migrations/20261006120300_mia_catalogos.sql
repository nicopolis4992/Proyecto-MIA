-- =============================================================================
-- SCRUM-74 · Archivo 003 (migración 4/7 de Supabase): datos de catálogo y configuración inicial
-- Los valores marcados «POR CONFIRMAR» NO deben aparecer en el informe como
-- datos del negocio hasta que la propietaria los valide.
-- =============================================================================
SET ROLE mia_duenio;
SET search_path = mia, public;

-- Códigos de servicio que el negocio ya usa en su Excel (catálogo de SCRUM-72).
-- El significado de cada sigla no está documentado en el catálogo: POR CONFIRMAR.
INSERT INTO servicio (codigo, descripcion) VALUES
    ('SC',   NULL), ('SB', NULL), ('SP', NULL), ('BA', NULL),
    ('BM',   NULL), ('BB', NULL), ('SBas', NULL);

-- [tarifario v2] Servicios del catálogo de la propietaria (app/cotizacion/tarifario_v2.json).
-- La equivalencia con las siglas del Excel sigue pendiente (H2, Daniel Ocampo).
INSERT INTO servicio (codigo, descripcion, fuente) VALUES
    ('express',   'Baño Express (desde USD 7)',   'tarifario_v2'),
    ('basico',    'Baño Básico (desde USD 9)',    'tarifario_v2'),
    ('completo',  'Baño Completo (desde USD 12)', 'tarifario_v2'),
    ('premium',   'Baño Premium (desde USD 15)',  'tarifario_v2'),
    ('deslanado', 'Deslanado (servicio especial)', 'tarifario_v2');

-- Canales de captación (columna ORIGEN, presente en las 28 hojas del Excel).
INSERT INTO origen (codigo, descripcion) VALUES
    ('LINAS',     'Cliente directo de Lina''s Pet Salón'),
    ('LAVET',     'Derivado desde Lavet'),
    ('HOSPEDAJE', 'Proveniente del servicio de hospedaje');

-- Transiciones permitidas: quién puede mover la cita de un estado a otro.
INSERT INTO transicion_estado (desde, hacia, rol_requerido, actor) VALUES
    ('pendiente_aprobacion', 'aprobada',   'mia_aprobacion', 'propietaria'),
    ('pendiente_aprobacion', 'rechazada',  'mia_aprobacion', 'propietaria'),
    ('pendiente_aprobacion', 'expirada',   'mia_sistema',    'sistema'),
    ('aprobada',             'confirmada', 'mia_sistema',    'sistema');

-- [prototipo] Flujo del cliente. El agente actúa en nombre del CLIENTE, nunca
-- de la propietaria: puede aceptar lo que ella propuso, pedir otro horario o
-- cancelar, pero no aprobar una propuesta que ella no haya visto.
INSERT INTO transicion_estado (desde, hacia, rol_requerido, actor, cambia_propuesta) VALUES
    ('pendiente_aprobacion', 'propuesta_cliente',    'mia_aprobacion', 'propietaria', true),
    ('propuesta_cliente',    'aprobada',             'mia_agente',     'cliente',     false),
    ('propuesta_cliente',    'expirada',             'mia_sistema',    'sistema',     false),
    ('en_reprogramacion',    'pendiente_aprobacion', 'mia_agente',     'cliente',     true),
    ('en_reprogramacion',    'expirada',             'mia_sistema',    'sistema',     false),
    ('pendiente_aprobacion', 'en_reprogramacion',    'mia_agente',     'cliente',     false),
    ('propuesta_cliente',    'en_reprogramacion',    'mia_agente',     'cliente',     false),
    ('aprobada',             'en_reprogramacion',    'mia_agente',     'cliente',     false),
    ('confirmada',           'en_reprogramacion',    'mia_agente',     'cliente',     false),
    ('pendiente_aprobacion', 'cancelada',            'mia_agente',     'cliente',     false),
    ('propuesta_cliente',    'cancelada',            'mia_agente',     'cliente',     false),
    ('aprobada',             'cancelada',            'mia_agente',     'cliente',     false),
    ('confirmada',           'cancelada',            'mia_agente',     'cliente',     false),
    ('en_reprogramacion',    'cancelada',            'mia_agente',     'cliente',     false);
-- No existe ninguna fila que lleve a «confirmada» desde «pendiente_aprobacion»:
-- saltarse a la propietaria es imposible, no solo desaconsejado.

-- Reparto de ingresos observado en el registro contable (catálogo de SCRUM-72).
-- Fechas: primera hoja disponible (sept-2024) y cambio de fórmula (sept-2026).
-- Qué beneficiario recibe cada porcentaje: POR CONFIRMAR con la propietaria.
WITH v AS (
    INSERT INTO reparto_version (vigente_desde, nota)
    VALUES ('2024-09-01', 'Fórmula 20/80 observada en las hojas 2024-2025')
    RETURNING reparto_id
)
INSERT INTO reparto_participacion (reparto_id, beneficiario, porcentaje)
SELECT reparto_id, b, pct FROM v, (VALUES ('beneficiario_A', 20.00), ('beneficiario_B', 80.00)) AS t(b, pct);

WITH v AS (
    INSERT INTO reparto_version (vigente_desde, nota)
    VALUES ('2026-09-01', 'Fórmula 20/70/10 con nuevo beneficiario («Mami»); asignación de porcentajes POR CONFIRMAR')
    RETURNING reparto_id
)
INSERT INTO reparto_participacion (reparto_id, beneficiario, porcentaje)
SELECT reparto_id, b, pct FROM v, (VALUES ('beneficiario_A', 20.00), ('beneficiario_B', 70.00), ('Mami', 10.00)) AS t(b, pct);
