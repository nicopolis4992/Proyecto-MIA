-- =============================================================================
-- SCRUM-74 · Archivo 002 (migración 3/7 de Supabase): reglas de negocio en la base de datos
--   * máquina de estados (human-in-the-loop garantizado por roles)
--   * congelamiento de lo aprobado
--   * historial automático e inmutable
--   * funciones de escritura: la ÚNICA puerta de entrada para la aplicación
-- =============================================================================
SET ROLE mia_duenio;
SET search_path = mia, public;

-- -----------------------------------------------------------------------------
-- 1. Roles: creados en 000_admin.sql
-- -----------------------------------------------------------------------------
-- mia_agente     → agente conversacional con el cliente: SOLO registra propuestas.
-- mia_aprobacion → canal que recibe la respuesta de la propietaria (SCRUM-77).
-- mia_sistema    → procesos automáticos: expirar sin respuesta (SCRUM-76) y
--                  marcar como confirmada tras avisar al cliente (SCRUM-78).
-- mia_lectura    → resúmenes y métricas (SCRUM-75, SCRUM-90, SCRUM-95).

-- -----------------------------------------------------------------------------
-- 2. Foto de la propuesta (lo que la propietaria ve y aprueba)
-- -----------------------------------------------------------------------------
CREATE FUNCTION fn_foto_propuesta(p_cita bigint) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = mia, pg_temp AS $$
    SELECT jsonb_build_object(
        'version',            c.version,
        'estado',             c.estado,
        'inicio',             lower(c.horario_propuesto),
        'fin',                upper(c.horario_propuesto),
        'origen',             c.origen_codigo,
        'puerta_a_puerta',    c.puerta_a_puerta,
        'costo_traslado',     c.costo_traslado,
        'descuento_tipo',     c.descuento_tipo,
        'descuento_detalle',  c.descuento_detalle,
        'descuento_monto',    c.descuento_monto,
        'tarifario_version',  c.tarifario_version,
        'lineas', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                       'linea', l.linea, 'mascota_id', l.mascota_id,
                       'servicio', l.servicio_codigo,
                       'precio_estimado', l.precio_estimado,
                       'semiamplitud', l.semiamplitud,
                       'es_comprometido', l.es_comprometido,
                       'atributos_no_declarados', to_jsonb(l.atributos_no_declarados))
                   ORDER BY l.linea)
            FROM cita_linea l WHERE l.cita_id = c.cita_id), '[]'::jsonb)
    )
    FROM cita c WHERE c.cita_id = p_cita;
$$;

-- -----------------------------------------------------------------------------
-- 3. Disparadores sobre la cita
-- -----------------------------------------------------------------------------
-- 3.1 Criterio de aceptación: toda cita NACE pendiente de aprobación.
CREATE FUNCTION trg_cita_nace_pendiente() RETURNS trigger
LANGUAGE plpgsql SET search_path = mia, pg_temp AS $$
BEGIN
    IF NEW.estado <> 'pendiente_aprobacion' OR NEW.version <> 1 THEN
        RAISE EXCEPTION 'Una cita solo puede registrarse como pendiente_aprobacion (versión 1); se recibió % (v%)',
            NEW.estado, NEW.version
            USING ERRCODE = 'check_violation', HINT = 'La aprobación es exclusiva de la propietaria.';
    END IF;
    NEW.ultimo_actor := 'agente';
    IF lower(NEW.horario_propuesto) <= now() THEN
        RAISE EXCEPTION 'El horario propuesto (%) ya pasó', lower(NEW.horario_propuesto)
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER cita_nace_pendiente BEFORE INSERT ON cita
    FOR EACH ROW EXECUTE FUNCTION trg_cita_nace_pendiente();

-- 3.2 Transiciones válidas y congelamiento de lo aprobado.
--     Regla: «lo que se aprueba es exactamente lo que se confirma».
CREATE FUNCTION trg_cita_controla_cambios() RETURNS trigger
LANGUAGE plpgsql SET search_path = mia, pg_temp AS $$
DECLARE
    cambio_negocio boolean;
    v_cambia       boolean;
BEGIN
    cambio_negocio :=
           NEW.horario_propuesto IS DISTINCT FROM OLD.horario_propuesto
        OR NEW.puerta_a_puerta   IS DISTINCT FROM OLD.puerta_a_puerta
        OR NEW.costo_traslado    IS DISTINCT FROM OLD.costo_traslado
        OR NEW.direccion_cifrada IS DISTINCT FROM OLD.direccion_cifrada
        OR NEW.dentro_perimetro_urbano IS DISTINCT FROM OLD.dentro_perimetro_urbano
        OR NEW.descuento_tipo    IS DISTINCT FROM OLD.descuento_tipo
        OR NEW.descuento_detalle IS DISTINCT FROM OLD.descuento_detalle
        OR NEW.descuento_monto   IS DISTINCT FROM OLD.descuento_monto
        OR NEW.solicitante_id    IS DISTINCT FROM OLD.solicitante_id
        OR NEW.origen_codigo     IS DISTINCT FROM OLD.origen_codigo
        OR NEW.tarifario_version IS DISTINCT FROM OLD.tarifario_version
        OR NEW.clave_idempotencia IS DISTINCT FROM OLD.clave_idempotencia
        OR NEW.registrado_en     IS DISTINCT FROM OLD.registrado_en
        OR NEW.sector            IS DISTINCT FROM OLD.sector            -- [prototipo]
        OR NEW.pedido_especial   IS DISTINCT FROM OLD.pedido_especial;  -- [prototipo]

    IF NEW.estado = OLD.estado AND NEW.version = OLD.version THEN
        IF cambio_negocio THEN
            RAISE EXCEPTION 'Cambiar la propuesta exige una nueva versión (fn_reproponer); la cita % está en v%',
                OLD.cita_id, OLD.version USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.estado = OLD.estado THEN
        -- Solo la «modificación y repropuesta» mantiene el estado y sube la versión.
        IF OLD.estado <> 'pendiente_aprobacion' OR NEW.version <> OLD.version + 1 THEN
            RAISE EXCEPTION 'Cambio de versión inválido (v% → v%) en estado %', OLD.version, NEW.version, OLD.estado
                USING ERRCODE = 'check_violation';
        END IF;
    ELSE
        SELECT t.cambia_propuesta INTO v_cambia
          FROM transicion_estado t WHERE t.desde = OLD.estado AND t.hacia = NEW.estado;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Transición no permitida: % → %', OLD.estado, NEW.estado
                USING ERRCODE = 'check_violation';
        END IF;
        IF v_cambia THEN
            -- [prototipo] Transiciones que llevan una propuesta NUEVA (la propietaria
            -- la cambia para el cliente, o el cliente elige otro horario): la
            -- versión sube exactamente en uno, para que nadie apruebe la anterior.
            IF NEW.version <> OLD.version + 1 THEN
                RAISE EXCEPTION 'La transición % → % exige subir la versión (v% → v%)',
                    OLD.estado, NEW.estado, OLD.version, OLD.version + 1 USING ERRCODE = 'check_violation';
            END IF;
        ELSIF NEW.version <> OLD.version OR cambio_negocio THEN
            RAISE EXCEPTION 'Un cambio de estado no puede alterar la propuesta que se aprobó'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;

    IF NEW.horario_propuesto IS DISTINCT FROM OLD.horario_propuesto AND lower(NEW.horario_propuesto) <= now() THEN
        RAISE EXCEPTION 'El nuevo horario (%) ya pasó', lower(NEW.horario_propuesto) USING ERRCODE = 'check_violation';
    END IF;

    NEW.actualizado_en := now();
    RETURN NEW;
END $$;

CREATE TRIGGER cita_controla_cambios BEFORE UPDATE ON cita
    FOR EACH ROW EXECUTE FUNCTION trg_cita_controla_cambios();

CREATE FUNCTION trg_cita_no_se_borra() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Las citas no se eliminan: se rechazan o expiran (trazabilidad)'
        USING ERRCODE = 'restrict_violation';
END $$;

CREATE TRIGGER cita_no_se_borra BEFORE DELETE ON cita
    FOR EACH ROW EXECUTE FUNCTION trg_cita_no_se_borra();

-- 3.3 Las líneas solo se tocan mientras la cita sigue pendiente.
CREATE FUNCTION trg_linea_solo_si_pendiente() RETURNS trigger
LANGUAGE plpgsql SET search_path = mia, pg_temp AS $$
DECLARE
    v_estado estado_cita;
BEGIN
    SELECT estado INTO v_estado FROM cita WHERE cita_id = COALESCE(NEW.cita_id, OLD.cita_id);
    IF v_estado IS DISTINCT FROM 'pendiente_aprobacion' THEN
        RAISE EXCEPTION 'La cita % está %: sus líneas ya no pueden modificarse', COALESCE(NEW.cita_id, OLD.cita_id), v_estado
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN COALESCE(NEW, OLD);
END $$;

CREATE TRIGGER linea_solo_si_pendiente BEFORE INSERT OR UPDATE OR DELETE ON cita_linea
    FOR EACH ROW EXECUTE FUNCTION trg_linea_solo_si_pendiente();

-- 3.4 Coherencia de montos, verificada AL CONFIRMAR LA TRANSACCIÓN (diferida),
--     cuando cabecera y líneas ya están completas.
CREATE FUNCTION trg_cita_coherente() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = mia, pg_temp AS $$
DECLARE
    v_cita     bigint := COALESCE(NEW.cita_id, OLD.cita_id);
    v_lineas   integer;
    v_subtotal numeric;
    v_desc     numeric;
BEGIN
    SELECT count(*), COALESCE(sum(precio_estimado), 0) INTO v_lineas, v_subtotal
      FROM cita_linea WHERE cita_id = v_cita;
    SELECT descuento_monto INTO v_desc FROM cita WHERE cita_id = v_cita;
    IF v_desc IS NULL THEN RETURN NULL; END IF;       -- la cita no existe (no aplica)
    IF v_lineas = 0 THEN
        RAISE EXCEPTION 'La cita % no tiene ninguna mascota/servicio', v_cita USING ERRCODE = 'check_violation';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM cita_evento e WHERE e.cita_id = v_cita AND e.estado_anterior IS NULL) THEN
        RAISE EXCEPTION 'La cita % no tiene evento de alta: use fn_registrar_cita', v_cita USING ERRCODE = 'check_violation';
    END IF;
    IF v_desc > v_subtotal THEN
        RAISE EXCEPTION 'El descuento (%) supera el subtotal de servicios (%) en la cita %', v_desc, v_subtotal, v_cita
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER cita_coherente AFTER INSERT OR UPDATE ON cita
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_cita_coherente();
CREATE CONSTRAINT TRIGGER linea_coherente AFTER INSERT OR UPDATE OR DELETE ON cita_linea
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_cita_coherente();

-- 3.5 Historial automático de CAMBIOS: ningún cambio de estado o versión
--     queda sin evento. Es inmediato, para que la foto refleje la propuesta en
--     el instante del cambio. El evento de ALTA lo escribe fn_registrar_cita
--     cuando ya insertó las líneas; la verificación diferida (3.4) impide que
--     exista una cita sin su evento de alta.
CREATE FUNCTION trg_cita_registra_evento() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = mia, pg_temp AS $$
BEGIN
    IF NEW.estado = OLD.estado AND NEW.version = OLD.version THEN
        RETURN NULL;
    END IF;
    INSERT INTO cita_evento (cita_id, version, estado_anterior, estado_nuevo, actor, evidencia, foto_propuesta)
    VALUES (NEW.cita_id, NEW.version, OLD.estado, NEW.estado,
            NEW.ultimo_actor, NEW.ultima_evidencia, fn_foto_propuesta(NEW.cita_id));
    RETURN NULL;
END $$;

CREATE TRIGGER cita_registra_evento AFTER UPDATE ON cita
    FOR EACH ROW EXECUTE FUNCTION trg_cita_registra_evento();

-- 3.6 El historial es de solo inserción.
CREATE FUNCTION trg_inmutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'La tabla % es de solo inserción', TG_TABLE_NAME USING ERRCODE = 'restrict_violation';
END $$;

CREATE TRIGGER evento_inmutable BEFORE UPDATE OR DELETE ON cita_evento
    FOR EACH ROW EXECUTE FUNCTION trg_inmutable();
CREATE TRIGGER evento_sin_truncate BEFORE TRUNCATE ON cita_evento
    FOR EACH STATEMENT EXECUTE FUNCTION trg_inmutable();

-- -----------------------------------------------------------------------------
-- 4. Reparto de ingresos: suma 100 % y versiones vigentes intocables
-- -----------------------------------------------------------------------------
CREATE FUNCTION trg_reparto_suma_100() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = mia, pg_temp AS $$
DECLARE
    v_id    integer := COALESCE(NEW.reparto_id, OLD.reparto_id);
    v_suma  numeric;
BEGIN
    SELECT sum(porcentaje) INTO v_suma FROM reparto_participacion WHERE reparto_id = v_id;
    IF v_suma IS NOT NULL AND v_suma <> 100 THEN
        RAISE EXCEPTION 'El reparto % suma % %% (debe sumar 100 %%)', v_id, v_suma USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER reparto_suma_100 AFTER INSERT OR UPDATE OR DELETE ON reparto_participacion
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION trg_reparto_suma_100();

CREATE FUNCTION trg_reparto_vigente_inmutable() RETURNS trigger
LANGUAGE plpgsql SET search_path = mia, pg_temp AS $$
BEGIN
    IF (SELECT vigente_desde FROM reparto_version WHERE reparto_id = OLD.reparto_id) <= current_date THEN
        RAISE EXCEPTION 'El reparto % ya entró en vigencia: registre una versión nueva en lugar de editarlo', OLD.reparto_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN COALESCE(NEW, OLD);
END $$;

CREATE TRIGGER reparto_vigente_inmutable BEFORE UPDATE OR DELETE ON reparto_participacion
    FOR EACH ROW EXECUTE FUNCTION trg_reparto_vigente_inmutable();

CREATE FUNCTION fn_reparto_vigente(p_fecha date)
RETURNS TABLE (vigente_desde date, beneficiario text, porcentaje numeric)
LANGUAGE sql STABLE SET search_path = mia, pg_temp AS $$
    SELECT v.vigente_desde, p.beneficiario, p.porcentaje
      FROM reparto_version v JOIN reparto_participacion p USING (reparto_id)
     WHERE v.reparto_id = (SELECT reparto_id FROM reparto_version
                            WHERE vigente_desde <= p_fecha
                            ORDER BY vigente_desde DESC LIMIT 1)
     ORDER BY p.porcentaje DESC, p.beneficiario;
$$;

-- -----------------------------------------------------------------------------
-- 5. Funciones de escritura (SECURITY DEFINER, search_path fijo)
-- -----------------------------------------------------------------------------
-- 5.1 Registrar la cita propuesta. Recibe los datos YA seudonimizados/cifrados
--     por la aplicación (la base nunca recibe el teléfono en claro).
--     Idempotente: la misma clave devuelve la cita existente y creada = false.
--     Motivo: Meta reintenta los webhooks fallidos durante 36 h y exige que el
--     servidor deduplique (Meta for Developers, «Webhooks – Getting Started»).
CREATE FUNCTION fn_registrar_cita(p jsonb)
RETURNS TABLE (cita_id bigint, creada boolean)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = mia, pg_temp AS $$
DECLARE
    v_clave        text := p->>'clave_idempotencia';
    v_cita         bigint;
    v_solicitante  bigint;
    v_referente    bigint;
    v_propietario  bigint;
    v_mascota      bigint;
    v_linea        jsonb;
    v_prop         jsonb;
    v_n            smallint := 0;
BEGIN
    IF v_clave IS NULL OR btrim(v_clave) = '' THEN
        RAISE EXCEPTION 'Falta clave_idempotencia' USING ERRCODE = 'not_null_violation';
    END IF;
    IF jsonb_typeof(p->'lineas') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'lineas') = 0 THEN
        RAISE EXCEPTION 'La propuesta debe incluir al menos una mascota' USING ERRCODE = 'check_violation';
    END IF;

    -- Reintento del mismo mensaje: no se duplica nada.
    SELECT c.cita_id INTO v_cita FROM cita c WHERE c.clave_idempotencia = v_clave;
    IF FOUND THEN
        RETURN QUERY SELECT v_cita, false; RETURN;
    END IF;

    -- Referente (quien recomendó al solicitante), si ya es cliente.
    IF p->'solicitante' ? 'referido_por_hmac' THEN
        SELECT cl.cliente_id INTO v_referente FROM cliente cl
         WHERE cl.identificador_hmac = p->'solicitante'->>'referido_por_hmac';
    END IF;

    -- Solicitante: el contacto que escribe por WhatsApp.
    INSERT INTO cliente AS cl (identificador_hmac, tipo_identificador, telefono_cifrado, nombre_cifrado, referido_por)
    VALUES (p->'solicitante'->>'identificador_hmac', 'telefono',
            decode(p->'solicitante'->>'telefono_cifrado', 'base64'),
            decode(p->'solicitante'->>'nombre_cifrado', 'base64'),
            v_referente)
    ON CONFLICT (identificador_hmac) DO UPDATE
        SET telefono_cifrado = EXCLUDED.telefono_cifrado,
            nombre_cifrado   = EXCLUDED.nombre_cifrado,
            referido_por     = COALESCE(cl.referido_por, EXCLUDED.referido_por)
    RETURNING cl.cliente_id INTO v_solicitante;

    INSERT INTO cita AS c (solicitante_id, origen_codigo, horario_propuesto,
                           puerta_a_puerta, costo_traslado, direccion_cifrada, dentro_perimetro_urbano,
                           descuento_tipo, descuento_detalle, descuento_monto,
                           tarifario_version, clave_idempotencia,
                           sector, pedido_especial, requiere_revision_manual)   -- [prototipo]
    VALUES (v_solicitante,
            p->>'origen',
            tstzrange((p->>'horario_inicio')::timestamptz, (p->>'horario_fin')::timestamptz, '[)'),
            COALESCE((p->>'puerta_a_puerta')::boolean, false),
            COALESCE((p->>'costo_traslado')::numeric, 0),
            decode(p->>'direccion_cifrada', 'base64'),
            (p->>'dentro_perimetro_urbano')::boolean,
            p->'descuento'->>'tipo',
            p->'descuento'->>'detalle',
            COALESCE((p->'descuento'->>'monto')::numeric, 0),
            p->>'tarifario_version',
            v_clave,
            NULLIF(btrim(p->>'sector'), ''),
            NULLIF(btrim(p->>'pedido_especial'), ''),
            COALESCE((p->>'requiere_revision_manual')::boolean, false))
    ON CONFLICT (clave_idempotencia) DO NOTHING
    RETURNING c.cita_id INTO v_cita;

    IF v_cita IS NULL THEN   -- otra transacción ganó la carrera con la misma clave
        SELECT c.cita_id INTO v_cita FROM cita c WHERE c.clave_idempotencia = v_clave;
        RETURN QUERY SELECT v_cita, false; RETURN;
    END IF;

    FOR v_linea IN SELECT value FROM jsonb_array_elements(p->'lineas') LOOP
        v_n := v_n + 1;
        v_prop := v_linea->'mascota'->'propietario';

        -- Dueño de la mascota: el propio solicitante o un tercero referido.
        IF v_prop IS NULL OR v_prop = '"solicitante"'::jsonb THEN
            v_propietario := v_solicitante;
        ELSE
            INSERT INTO cliente AS cl (identificador_hmac, tipo_identificador, telefono_cifrado, nombre_cifrado, referido_por)
            VALUES (v_prop->>'identificador_hmac',
                    COALESCE(v_prop->>'tipo_identificador', 'tercero'),
                    decode(v_prop->>'telefono_cifrado', 'base64'),
                    decode(v_prop->>'nombre_cifrado', 'base64'),
                    v_solicitante)
            ON CONFLICT (identificador_hmac) DO UPDATE
                SET nombre_cifrado = EXCLUDED.nombre_cifrado,
                    referido_por   = COALESCE(cl.referido_por, EXCLUDED.referido_por)
            RETURNING cl.cliente_id INTO v_propietario;
        END IF;

        INSERT INTO mascota AS m (propietario_id, nombre, raza, temperamento)
        VALUES (v_propietario, btrim(v_linea->'mascota'->>'nombre'),
                v_linea->'mascota'->>'raza', v_linea->'mascota'->>'temperamento')
        ON CONFLICT (propietario_id, lower(btrim(nombre))) DO UPDATE
            SET raza         = COALESCE(EXCLUDED.raza, m.raza),
                temperamento = COALESCE(EXCLUDED.temperamento, m.temperamento)
        RETURNING m.mascota_id INTO v_mascota;

        INSERT INTO cita_linea (cita_id, linea, mascota_id, servicio_codigo, precio_estimado,
                                semiamplitud, es_comprometido, atributos_no_declarados, desglose)
        VALUES (v_cita, v_n, v_mascota, v_linea->>'servicio',
                (v_linea->>'precio_estimado')::numeric,
                COALESCE((v_linea->>'semiamplitud')::numeric, 0),
                (v_linea->>'es_comprometido')::boolean,
                COALESCE(ARRAY(SELECT jsonb_array_elements_text(v_linea->'atributos_no_declarados')), '{}'),
                COALESCE(v_linea->'desglose', '{}'::jsonb));
    END LOOP;

    INSERT INTO cita_evento (cita_id, version, estado_anterior, estado_nuevo, actor, evidencia, foto_propuesta)
    VALUES (v_cita, 1, NULL, 'pendiente_aprobacion', 'agente', NULL, fn_foto_propuesta(v_cita));

    RETURN QUERY SELECT v_cita, true;
END $$;

-- 5.2 Cambiar de estado. Exige la versión que el actor tiene a la vista
--     (control optimista): aprobar la v1 cuando ya existe una v2 falla.
CREATE FUNCTION fn_cambiar_estado(p_cita bigint, p_version_esperada integer,
                                  p_hacia estado_cita, p_evidencia text DEFAULT NULL)
RETURNS estado_cita
LANGUAGE plpgsql SECURITY DEFINER SET search_path = mia, pg_temp AS $$
DECLARE
    v_actual  cita%ROWTYPE;
    v_regla   transicion_estado%ROWTYPE;
BEGIN
    SELECT * INTO v_actual FROM cita WHERE cita_id = p_cita FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe la cita %', p_cita USING ERRCODE = 'no_data_found';
    END IF;
    IF v_actual.version <> p_version_esperada THEN
        RAISE EXCEPTION 'Versión obsoleta: se esperaba v% pero la cita % está en v%',
            p_version_esperada, p_cita, v_actual.version
            USING ERRCODE = 'serialization_failure',
                  HINT = 'La propuesta cambió; envíe el resumen actualizado a la propietaria.';
    END IF;

    SELECT * INTO v_regla FROM transicion_estado WHERE desde = v_actual.estado AND hacia = p_hacia;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Transición no permitida: % → %', v_actual.estado, p_hacia USING ERRCODE = 'check_violation';
    END IF;
    IF v_regla.cambia_propuesta THEN
        RAISE EXCEPTION 'La transición % → % cambia la propuesta: use fn_proponer_al_cliente o fn_reprogramar',
            v_actual.estado, p_hacia USING ERRCODE = 'check_violation';
    END IF;

    -- Autorización por el rol de la CONEXIÓN (session_user), no por lo que el
    -- llamador afirme ser. Dentro de SECURITY DEFINER, current_user es el dueño.
    IF NOT pg_has_role(session_user, v_regla.rol_requerido, 'MEMBER') THEN
        RAISE EXCEPTION 'El rol % no está autorizado para % → % (requiere %)',
            session_user, v_actual.estado, p_hacia, v_regla.rol_requerido
            USING ERRCODE = 'insufficient_privilege';
    END IF;

    UPDATE cita SET estado = p_hacia, ultimo_actor = v_regla.actor, ultima_evidencia = p_evidencia
     WHERE cita_id = p_cita;
    RETURN p_hacia;
END $$;

-- 5.3 Modificar y reproponer (tercer camino de SCRUM-77): la propietaria ajusta
--     hora, traslado, descuento o precio de una línea; la cita sube de versión
--     y vuelve a un ciclo de aprobación.
CREATE FUNCTION fn_reproponer(p_cita bigint, p_version_esperada integer,
                              p_cambios jsonb, p_evidencia text DEFAULT NULL)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = mia, pg_temp AS $$
DECLARE
    v_actual cita%ROWTYPE;
    v_l      jsonb;
BEGIN
    IF NOT pg_has_role(session_user, 'mia_aprobacion', 'MEMBER') THEN
        RAISE EXCEPTION 'Solo el canal de la propietaria puede modificar una propuesta' USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT * INTO v_actual FROM cita WHERE cita_id = p_cita FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe la cita %', p_cita USING ERRCODE = 'no_data_found';
    END IF;
    IF v_actual.version <> p_version_esperada THEN
        RAISE EXCEPTION 'Versión obsoleta: se esperaba v% pero la cita % está en v%', p_version_esperada, p_cita, v_actual.version
            USING ERRCODE = 'serialization_failure';
    END IF;
    IF v_actual.estado <> 'pendiente_aprobacion' THEN
        RAISE EXCEPTION 'Solo se modifica una cita pendiente; la cita % está %', p_cita, v_actual.estado
            USING ERRCODE = 'check_violation';
    END IF;

    FOR v_l IN SELECT value FROM jsonb_array_elements(COALESCE(p_cambios->'lineas', '[]'::jsonb)) LOOP
        UPDATE cita_linea
           SET precio_estimado = COALESCE((v_l->>'precio_estimado')::numeric, precio_estimado),
               semiamplitud    = COALESCE((v_l->>'semiamplitud')::numeric, semiamplitud),
               es_comprometido = COALESCE((v_l->>'es_comprometido')::boolean, es_comprometido)
         WHERE cita_id = p_cita AND linea = (v_l->>'linea')::smallint;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'La cita % no tiene la línea %', p_cita, v_l->>'linea' USING ERRCODE = 'no_data_found';
        END IF;
    END LOOP;

    UPDATE cita SET
        version           = version + 1,
        ultimo_actor      = 'propietaria',
        ultima_evidencia  = p_evidencia,
        horario_propuesto = CASE WHEN p_cambios ? 'horario_inicio'
                                 THEN tstzrange((p_cambios->>'horario_inicio')::timestamptz,
                                                (p_cambios->>'horario_fin')::timestamptz, '[)')
                                 ELSE horario_propuesto END,
        costo_traslado    = COALESCE((p_cambios->>'costo_traslado')::numeric, costo_traslado),
        descuento_tipo    = CASE WHEN p_cambios ? 'descuento' THEN p_cambios->'descuento'->>'tipo' ELSE descuento_tipo END,
        descuento_detalle = CASE WHEN p_cambios ? 'descuento' THEN p_cambios->'descuento'->>'detalle' ELSE descuento_detalle END,
        descuento_monto   = CASE WHEN p_cambios ? 'descuento'
                                 THEN COALESCE((p_cambios->'descuento'->>'monto')::numeric, 0) ELSE descuento_monto END
     WHERE cita_id = p_cita;

    RETURN v_actual.version + 1;
END $$;

-- 5.4 [prototipo] La propietaria cambia hora, traslado, descuento o precio y se
--     lo PROPONE AL CLIENTE (estado propuesta_cliente). Su cambio es su
--     aprobación: si el cliente acepta, la cita pasa a «aprobada» sin volver a
--     preguntarle. Si el cliente no acepta, pide otro horario o cancela.
CREATE FUNCTION fn_proponer_al_cliente(p_cita bigint, p_version_esperada integer,
                                       p_cambios jsonb, p_evidencia text DEFAULT NULL)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = mia, pg_temp AS $$
DECLARE
    v_actual cita%ROWTYPE;
    v_l      jsonb;
BEGIN
    IF NOT pg_has_role(session_user, 'mia_aprobacion', 'MEMBER') THEN
        RAISE EXCEPTION 'Solo el canal de la propietaria puede proponer cambios al cliente'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT * INTO v_actual FROM cita WHERE cita_id = p_cita FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe la cita %', p_cita USING ERRCODE = 'no_data_found';
    END IF;
    IF v_actual.version <> p_version_esperada THEN
        RAISE EXCEPTION 'Versión obsoleta: se esperaba v% pero la cita % está en v%', p_version_esperada, p_cita, v_actual.version
            USING ERRCODE = 'serialization_failure';
    END IF;
    IF v_actual.estado <> 'pendiente_aprobacion' THEN
        RAISE EXCEPTION 'Solo se propone un cambio sobre una cita pendiente; la cita % está %', p_cita, v_actual.estado
            USING ERRCODE = 'check_violation';
    END IF;

    -- Las líneas se ajustan mientras la cita sigue pendiente (trigger 3.3).
    FOR v_l IN SELECT value FROM jsonb_array_elements(COALESCE(p_cambios->'lineas', '[]'::jsonb)) LOOP
        UPDATE cita_linea
           SET precio_estimado = COALESCE((v_l->>'precio_estimado')::numeric, precio_estimado),
               semiamplitud    = COALESCE((v_l->>'semiamplitud')::numeric, semiamplitud),
               es_comprometido = COALESCE((v_l->>'es_comprometido')::boolean, es_comprometido)
         WHERE cita_id = p_cita AND linea = (v_l->>'linea')::smallint;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'La cita % no tiene la línea %', p_cita, v_l->>'linea' USING ERRCODE = 'no_data_found';
        END IF;
    END LOOP;

    UPDATE cita SET
        estado            = 'propuesta_cliente',
        version           = version + 1,
        ultimo_actor      = 'propietaria',
        ultima_evidencia  = p_evidencia,
        horario_propuesto = CASE WHEN p_cambios ? 'horario_inicio'
                                 THEN tstzrange((p_cambios->>'horario_inicio')::timestamptz,
                                                (p_cambios->>'horario_fin')::timestamptz, '[)')
                                 ELSE horario_propuesto END,
        costo_traslado    = COALESCE((p_cambios->>'costo_traslado')::numeric, costo_traslado),
        descuento_tipo    = CASE WHEN p_cambios ? 'descuento' THEN p_cambios->'descuento'->>'tipo' ELSE descuento_tipo END,
        descuento_detalle = CASE WHEN p_cambios ? 'descuento' THEN p_cambios->'descuento'->>'detalle' ELSE descuento_detalle END,
        descuento_monto   = CASE WHEN p_cambios ? 'descuento'
                                 THEN COALESCE((p_cambios->'descuento'->>'monto')::numeric, 0) ELSE descuento_monto END
     WHERE cita_id = p_cita;

    RETURN v_actual.version + 1;
END $$;

-- 5.5 [prototipo] El cliente eligió otro horario: la cita vuelve a la
--     propietaria como una versión nueva. Solo cambia el horario; el precio que
--     ella ya revisó se mantiene.
CREATE FUNCTION fn_reprogramar(p_cita bigint, p_version_esperada integer,
                               p_inicio timestamptz, p_fin timestamptz, p_evidencia text DEFAULT NULL)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = mia, pg_temp AS $$
DECLARE
    v_actual cita%ROWTYPE;
BEGIN
    IF NOT pg_has_role(session_user, 'mia_agente', 'MEMBER') THEN
        RAISE EXCEPTION 'Solo el agente conversacional registra el horario que elige el cliente'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT * INTO v_actual FROM cita WHERE cita_id = p_cita FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe la cita %', p_cita USING ERRCODE = 'no_data_found';
    END IF;
    IF v_actual.version <> p_version_esperada THEN
        RAISE EXCEPTION 'Versión obsoleta: se esperaba v% pero la cita % está en v%', p_version_esperada, p_cita, v_actual.version
            USING ERRCODE = 'serialization_failure';
    END IF;
    IF v_actual.estado <> 'en_reprogramacion' THEN
        RAISE EXCEPTION 'La cita % está %: primero debe pasar a en_reprogramacion', p_cita, v_actual.estado
            USING ERRCODE = 'check_violation';
    END IF;

    UPDATE cita SET
        estado            = 'pendiente_aprobacion',
        version           = version + 1,
        ultimo_actor      = 'cliente',
        ultima_evidencia  = p_evidencia,
        horario_propuesto = tstzrange(p_inicio, p_fin, '[)'),
        msg_aprobacion_id = NULL
     WHERE cita_id = p_cita;
    RETURN v_actual.version + 1;
END $$;

-- 5.6 [prototipo] Guarda el wamid del resumen enviado a la propietaria, para
--     reconocer su respuesta cuando cite ese mensaje. No cambia la propuesta.
CREATE FUNCTION fn_marcar_enviada_a_propietaria(p_cita bigint, p_msg_id text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = mia, pg_temp AS $$
BEGIN
    IF NOT (pg_has_role(session_user, 'mia_agente', 'MEMBER') OR pg_has_role(session_user, 'mia_sistema', 'MEMBER')) THEN
        RAISE EXCEPTION 'Rol no autorizado' USING ERRCODE = 'insufficient_privilege';
    END IF;
    UPDATE cita SET msg_aprobacion_id = p_msg_id WHERE cita_id = p_cita;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe la cita %', p_cita USING ERRCODE = 'no_data_found';
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 6. Vistas de lectura
-- -----------------------------------------------------------------------------
-- 6.1 Resumen con totales (insumo de SCRUM-75). El total NO se almacena: se
--     calcula, para que nunca diverja de sus líneas. La banda total suma las
--     semiamplitudes (cota conservadora: supone errores del mismo signo).
CREATE VIEW v_cita_resumen AS
SELECT c.cita_id, c.version, c.estado,
       lower(c.horario_propuesto) AS inicio, upper(c.horario_propuesto) AS fin,
       c.origen_codigo, c.puerta_a_puerta, c.dentro_perimetro_urbano,
       count(l.linea)                                                   AS n_mascotas,
       sum(l.precio_estimado)                                           AS subtotal_servicios,
       c.costo_traslado,
       c.descuento_tipo, c.descuento_detalle, c.descuento_monto,
       sum(l.precio_estimado) + c.costo_traslado - c.descuento_monto    AS total_estimado,
       sum(l.semiamplitud)                                              AS total_semiamplitud,
       bool_and(l.es_comprometido)                                      AS total_comprometido,
       c.tarifario_version, c.registrado_en, c.actualizado_en,
       c.sector, c.pedido_especial, c.requiere_revision_manual, c.msg_aprobacion_id   -- [prototipo]
  FROM cita c JOIN cita_linea l USING (cita_id)
 GROUP BY c.cita_id;

-- 6.2 Métricas del flujo de aprobación (insumo de SCRUM-90 y SCRUM-95).
CREATE VIEW v_metricas_aprobacion AS
SELECT c.cita_id, c.estado AS estado_actual, c.version AS versiones,
       c.registrado_en,
       d.ocurrido_en                                            AS primera_decision_en,
       d.estado_nuevo                                           AS primera_decision,
       round(extract(epoch FROM d.ocurrido_en - c.registrado_en) / 60.0, 1) AS minutos_hasta_decision,
       (SELECT count(*) FROM cita_evento e
         WHERE e.cita_id = c.cita_id AND e.estado_anterior = 'pendiente_aprobacion'
           AND e.estado_nuevo IN ('pendiente_aprobacion', 'propuesta_cliente'))  AS modificaciones_propietaria,
       (SELECT count(*) FROM cita_evento e
         WHERE e.cita_id = c.cita_id AND e.estado_nuevo = 'en_reprogramacion')    AS reprogramaciones_cliente
  FROM cita c
  LEFT JOIN LATERAL (
        SELECT e.ocurrido_en, e.estado_nuevo FROM cita_evento e
         WHERE e.cita_id = c.cita_id AND e.estado_nuevo IN ('aprobada', 'rechazada', 'expirada', 'propuesta_cliente')
         ORDER BY e.evento_id LIMIT 1) d ON true;

-- -----------------------------------------------------------------------------
-- 7. Permisos: la aplicación no escribe en tablas, solo invoca funciones.
--    (Por omisión PostgreSQL concede EXECUTE a PUBLIC: se revoca.)
-- -----------------------------------------------------------------------------
REVOKE ALL ON SCHEMA mia FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA mia FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA mia FROM PUBLIC;

GRANT USAGE ON SCHEMA mia TO mia_agente, mia_aprobacion, mia_sistema, mia_lectura;

GRANT EXECUTE ON FUNCTION fn_registrar_cita(jsonb)                                 TO mia_agente;
GRANT EXECUTE ON FUNCTION fn_cambiar_estado(bigint, integer, estado_cita, text)    TO mia_aprobacion, mia_sistema;
GRANT EXECUTE ON FUNCTION fn_reproponer(bigint, integer, jsonb, text)              TO mia_aprobacion;
-- [prototipo] El cliente acepta, pide reprogramar o cancela a través del agente.
GRANT EXECUTE ON FUNCTION fn_cambiar_estado(bigint, integer, estado_cita, text)    TO mia_agente;
GRANT EXECUTE ON FUNCTION fn_proponer_al_cliente(bigint, integer, jsonb, text)     TO mia_aprobacion;
GRANT EXECUTE ON FUNCTION fn_reprogramar(bigint, integer, timestamptz, timestamptz, text) TO mia_agente;
GRANT EXECUTE ON FUNCTION fn_marcar_enviada_a_propietaria(bigint, text)            TO mia_agente, mia_sistema;
GRANT EXECUTE ON FUNCTION fn_foto_propuesta(bigint)                                TO mia_lectura, mia_aprobacion;

GRANT SELECT ON v_cita_resumen TO mia_agente, mia_aprobacion, mia_sistema, mia_lectura;
GRANT SELECT ON v_metricas_aprobacion, cita_evento TO mia_lectura;
GRANT SELECT ON servicio, origen TO mia_agente, mia_aprobacion, mia_lectura;
-- El reparto de ingresos es información financiera de la propietaria:
-- el agente conversacional NO la lee.
GRANT EXECUTE ON FUNCTION fn_reparto_vigente(date) TO mia_lectura;
GRANT SELECT ON reparto_version, reparto_participacion TO mia_lectura;
