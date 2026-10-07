-- =============================================================================
-- Proyecto MIA · Lina's Pet Salón · Base de datos en Supabase
-- Migración 1/7: extensiones, roles y esquemas
--
-- Origen: sql/000_admin.sql de SCRUM-74, adaptado a Supabase:
--   * En Supabase el usuario `postgres` NO es superusuario. Tiene CREATEROLE,
--     así que puede crear los roles y concedérselos a sí mismo, pero no
--     `GRANT CREATE ON DATABASE`. Por eso los esquemas se crean aquí con
--     AUTHORIZATION mia_duenio en lugar de dejar que mia_duenio los cree.
--   * Las extensiones van en el esquema `extensions`, como recomienda Supabase.
--   * Los esquemas mia, mia_op y mia_rv NO se exponen en la API de datos
--     (PostgREST). La aplicación se conecta por PostgreSQL con un usuario por
--     servicio (ver db/supabase/usuarios_login.sql).
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA extensions;

DO $$
BEGIN
    -- Dueño de los objetos. Las funciones SECURITY DEFINER no deben pertenecer
    -- a un superusuario (PostgreSQL, «Writing SECURITY DEFINER Functions Safely»).
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mia_duenio')     THEN CREATE ROLE mia_duenio     NOLOGIN; END IF;
    -- Un rol por responsabilidad. La aprobación humana depende de QUIÉN se conecta.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mia_agente')     THEN CREATE ROLE mia_agente     NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mia_aprobacion') THEN CREATE ROLE mia_aprobacion NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mia_sistema')    THEN CREATE ROLE mia_sistema    NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mia_lectura')    THEN CREATE ROLE mia_lectura    NOLOGIN; END IF;
END $$;

-- Quien ejecuta las migraciones debe poder asumir mia_duenio (SET ROLE).
GRANT mia_duenio TO CURRENT_USER;

CREATE SCHEMA IF NOT EXISTS mia    AUTHORIZATION mia_duenio;   -- citas y aprobación (SCRUM-74)
CREATE SCHEMA IF NOT EXISTS mia_op AUTHORIZATION mia_duenio;   -- estado operativo del prototipo
CREATE SCHEMA IF NOT EXISTS mia_rv AUTHORIZATION mia_duenio;   -- restricción vehicular (SCRUM-73)
