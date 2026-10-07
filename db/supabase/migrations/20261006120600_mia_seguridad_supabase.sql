-- =============================================================================
-- Proyecto MIA · Migración 7/7: endurecimiento específico de Supabase
--
-- 1. Row Level Security en todas las tablas, como defensa en profundidad. Los
--    esquemas mia, mia_op y mia_rv no están expuestos en la API de datos, pero
--    si alguien los agrega por error en «Exposed schemas», los roles `anon` y
--    `authenticated` no deben poder leer ni escribir nada.
--    El dueño (mia_duenio) no está sujeto a RLS, así que las funciones SECURITY
--    DEFINER y las vistas siguen funcionando igual. Solo los roles que leen o
--    escriben tablas DIRECTAMENTE necesitan una política explícita.
-- 2. Revocación explícita para anon, authenticated y service_role.
-- =============================================================================
SET ROLE mia_duenio;

DO $$
DECLARE
    t record;
BEGIN
    FOR t IN SELECT schemaname, tablename FROM pg_tables
              WHERE schemaname IN ('mia', 'mia_op', 'mia_rv') LOOP
        EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', t.schemaname, t.tablename);
    END LOOP;
END $$;

-- Lecturas directas que ya concedía SCRUM-74
CREATE POLICY catalogo_lectura ON mia.servicio FOR SELECT TO mia_agente, mia_aprobacion, mia_lectura USING (true);
CREATE POLICY catalogo_lectura ON mia.origen   FOR SELECT TO mia_agente, mia_aprobacion, mia_lectura USING (true);
CREATE POLICY historial_lectura ON mia.cita_evento FOR SELECT TO mia_lectura USING (true);
CREATE POLICY reparto_lectura ON mia.reparto_version       FOR SELECT TO mia_lectura USING (true);
CREATE POLICY reparto_lectura ON mia.reparto_participacion FOR SELECT TO mia_lectura USING (true);

-- Estado operativo del prototipo
CREATE POLICY sesion_servicios ON mia_op.sesion FOR ALL TO mia_agente, mia_aprobacion USING (true) WITH CHECK (true);
CREATE POLICY cola_servicios ON mia_op.mensaje_saliente FOR ALL TO mia_agente, mia_aprobacion, mia_sistema
    USING (true) WITH CHECK (true);
CREATE POLICY dedupe_agente ON mia_op.mensaje_procesado FOR ALL TO mia_agente USING (true) WITH CHECK (true);

-- Restricción vehicular: solo lectura para quienes validan horarios
DO $$
DECLARE
    t record;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'mia_rv' LOOP
        EXECUTE format('CREATE POLICY lectura_servicios ON mia_rv.%I FOR SELECT TO mia_agente, mia_sistema USING (true)',
                       t.tablename);
    END LOOP;
END $$;

RESET ROLE;

-- Roles de la API de Supabase: sin ningún acceso a estos esquemas.
DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON SCHEMA mia, mia_op, mia_rv FROM %I', r);
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA mia, mia_op, mia_rv FROM %I', r);
            EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA mia, mia_op, mia_rv FROM %I', r);
        END IF;
    END LOOP;
END $$;
