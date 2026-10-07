-- =============================================================================
-- Proyecto MIA · Migración 5/7: estado operativo del prototipo (esquema mia_op)
--
-- Reemplaza las tablas de app/persistencia/repositorio.py (SQLite) que NO son
-- la cita: sesiones de conversación, cola de mensajes salientes (SCRUM-87) y
-- deduplicación de webhooks de Meta. La cita y su historial viven en `mia`.
--
-- Datos personales (LOPDP art. 10, minimización): el teléfono no se guarda en
-- claro. La sesión se busca por el HMAC del número (la misma clave de operación
-- de SCRUM-74) y los mensajes en cola se guardan cifrados por la aplicación
-- (Fernet), que es la única que tiene la clave. Las sesiones y la
-- deduplicación se purgan con fn_purgar_operacion().
-- =============================================================================
SET ROLE mia_duenio;
SET search_path = mia_op, pg_temp;

-- Estado de la conversación por número de WhatsApp.
CREATE TABLE sesion (
    telefono_hmac  char(64) PRIMARY KEY CHECK (telefono_hmac ~ '^[0-9a-f]{64}$'),
    datos          jsonb NOT NULL DEFAULT '{}'::jsonb,
    actualizada    timestamptz NOT NULL DEFAULT now()
);

-- Cola de salida (SCRUM-87): mensajes que no se pudieron enviar y se reintentan.
CREATE TABLE mensaje_saliente (
    mensaje_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    destino_cifrado  bytea  NOT NULL,
    cuerpo_cifrado   bytea  NOT NULL,
    estado           text   NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'enviado', 'fallido')),
    intentos         integer NOT NULL DEFAULT 1 CHECK (intentos >= 0),
    ultimo_error     text,
    creado           timestamptz NOT NULL DEFAULT now(),
    actualizado      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mensaje_pendiente ON mensaje_saliente (mensaje_id) WHERE estado = 'pendiente';

-- Deduplicación: Meta reintenta un webhook fallido hasta por 36 horas.
CREATE TABLE mensaje_procesado (
    wa_id   text PRIMARY KEY,
    fecha   timestamptz NOT NULL DEFAULT now()
);

-- Purga periódica (la ejecuta el proceso de mantenimiento con rol mia_sistema).
CREATE FUNCTION fn_purgar_operacion(p_dias_sesion integer DEFAULT 30, p_dias_dedupe integer DEFAULT 7)
RETURNS TABLE (sesiones_borradas bigint, procesados_borrados bigint, enviados_borrados bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = mia_op, pg_temp AS $$
DECLARE
    s bigint; p bigint; e bigint;
BEGIN
    IF p_dias_dedupe < 2 THEN
        RAISE EXCEPTION 'La deduplicación debe cubrir al menos 2 días (Meta reintenta hasta 36 h)'
            USING ERRCODE = 'check_violation';
    END IF;
    DELETE FROM sesion WHERE actualizada < now() - make_interval(days => p_dias_sesion);
    GET DIAGNOSTICS s = ROW_COUNT;
    DELETE FROM mensaje_procesado WHERE fecha < now() - make_interval(days => p_dias_dedupe);
    GET DIAGNOSTICS p = ROW_COUNT;
    DELETE FROM mensaje_saliente WHERE estado = 'enviado' AND actualizado < now() - make_interval(days => p_dias_sesion);
    GET DIAGNOSTICS e = ROW_COUNT;
    RETURN QUERY SELECT s, p, e;
END $$;

REVOKE ALL ON SCHEMA mia_op FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA mia_op FROM PUBLIC;
GRANT USAGE ON SCHEMA mia_op TO mia_agente, mia_aprobacion, mia_sistema;
-- El agente y el canal de la propietaria guardan sesiones; los tres usan la cola.
GRANT SELECT, INSERT, UPDATE, DELETE ON sesion TO mia_agente, mia_aprobacion;
GRANT SELECT, INSERT, UPDATE ON mensaje_saliente TO mia_agente, mia_aprobacion, mia_sistema;
GRANT SELECT, INSERT ON mensaje_procesado TO mia_agente;
GRANT EXECUTE ON FUNCTION fn_purgar_operacion(integer, integer) TO mia_sistema;
