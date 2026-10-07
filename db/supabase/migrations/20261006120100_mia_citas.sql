-- =============================================================================
-- Proyecto MIA · Lina's Pet Salón
-- SCRUM-74 — Registrar la cita propuesta en la base de datos
-- Archivo 001: esquema, restricciones e historial
-- Migración 2/7 de Supabase. Cambios respecto de SCRUM-74 (06/10/2026),
-- todos marcados con «[prototipo]» o «[tarifario v2]»:
--   * Estados que usa el prototipo: propuesta_cliente, en_reprogramacion, cancelada.
--   * Actor `cliente` (acepta una propuesta, pide reprogramar o cancela).
--   * Catálogo de servicios con los del tarifario v2, además de las siglas del Excel.
--   * Descuentos multi_mascota y fidelidad_mensual (tarifario v2).
--   * Columnas operativas de la cita: sector, pedido_especial,
--     requiere_revision_manual y msg_aprobacion_id.
--
-- Principio rector: la aprobación humana (human-in-the-loop) se garantiza en
-- la capa de persistencia, no en el prompt del agente. Ningún componente que
-- converse con el cliente puede, por construcción, dejar una cita confirmada.
-- Ref.: OWASP LLM06:2025 Excessive Agency — "Implement authorization in
-- downstream systems rather than relying on an LLM to decide if an action is
-- allowed".
-- =============================================================================

SET ROLE mia_duenio;   -- los objetos NO pertenecen a un superusuario
SET search_path = mia, public;   -- el esquema lo crea la migración 1

-- -----------------------------------------------------------------------------
-- 1. Estados del ciclo de vida de la cita
-- -----------------------------------------------------------------------------
-- pendiente_aprobacion → aprobada → confirmada        (camino feliz)
-- pendiente_aprobacion → rechazada                   (la propietaria no acepta)
-- pendiente_aprobacion → pendiente_aprobacion (v+1)  (modificar y reproponer, SCRUM-77)
-- pendiente_aprobacion → expirada                    (sin respuesta, SCRUM-76)
-- [prototipo] Flujo que ya implementa el prototipo de Nico:
-- pendiente_aprobacion → propuesta_cliente (v+1)     (la propietaria cambia hora o precio
--                                                     y se lo propone al cliente)
-- propuesta_cliente    → aprobada                    (el cliente acepta lo que ella propuso)
-- *                    → en_reprogramacion           (el cliente pide otro horario)
-- en_reprogramacion    → pendiente_aprobacion (v+1)  (nuevo horario: vuelve a la propietaria)
-- *                    → cancelada                   (el cliente cancela)
-- Sigue sin existir un camino a «confirmada» que no pase por una decisión de la
-- propietaria: «aprobada» solo se alcanza si ella aprueba o si el cliente acepta
-- una propuesta que ELLA hizo.
CREATE TYPE estado_cita AS ENUM (
    'pendiente_aprobacion', 'aprobada', 'rechazada', 'confirmada', 'expirada',
    'propuesta_cliente', 'en_reprogramacion', 'cancelada'
);

CREATE TYPE actor_cita AS ENUM ('agente', 'propietaria', 'sistema', 'cliente');

-- -----------------------------------------------------------------------------
-- 2. Catálogos (tablas, no enums: se editan sin migrar el esquema)
-- -----------------------------------------------------------------------------
CREATE TABLE servicio (
    -- [tarifario v2] admite las claves del tarifario (express, basico...) además
    -- de las siglas del Excel (SC, SB...). La equivalencia entre ambas sigue
    -- pendiente (H2): por eso conviven y se distinguen por `fuente`.
    codigo       text PRIMARY KEY CHECK (codigo ~ '^[A-Za-z][A-Za-z_]{1,19}$'),
    descripcion  text,                       -- NULL = pendiente de confirmar con la propietaria
    fuente       text NOT NULL DEFAULT 'excel' CHECK (fuente IN ('excel', 'tarifario_v2')),
    activo       boolean NOT NULL DEFAULT true
);

CREATE TABLE origen (
    codigo       text PRIMARY KEY,           -- canal de captación (columna ORIGEN del Excel)
    descripcion  text NOT NULL
);

-- Transiciones permitidas y ROL de base de datos que puede ejecutarlas.
-- La autorización depende de QUIÉN se conecta, no de lo que el agente declare.
CREATE TABLE transicion_estado (
    desde          estado_cita NOT NULL,
    hacia          estado_cita NOT NULL,
    rol_requerido  text        NOT NULL,
    actor          actor_cita  NOT NULL,
    -- [prototipo] La transición cambia la propuesta y sube la versión. Solo se
    -- ejecuta con la función dedicada (fn_proponer_al_cliente, fn_reprogramar).
    cambia_propuesta boolean   NOT NULL DEFAULT false,
    PRIMARY KEY (desde, hacia)
);

-- -----------------------------------------------------------------------------
-- 3. Personas y mascotas
-- -----------------------------------------------------------------------------
-- Minimización (LOPDP art. 10 lit. e) y seguridad (art. 37):
--   * identificador_hmac → seudónimo determinista para BUSCAR al cliente sin
--                          guardar su número (HMAC-SHA256, clave de operación).
--   * *_cifrado          → valor recuperable SOLO por la aplicación, que es la
--                          que debe responder por WhatsApp. La base nunca ve la
--                          clave de cifrado.
-- Referidos: un mismo contacto agenda para su prima o su vecina. Ese tercero
-- puede no tener teléfono registrado; se identifica entonces por un HMAC de
-- (teléfono de quien lo refiere + nombre normalizado) y queda enlazado a quien
-- lo refirió.
CREATE TABLE cliente (
    cliente_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    identificador_hmac  char(64) NOT NULL UNIQUE CHECK (identificador_hmac ~ '^[0-9a-f]{64}$'),
    tipo_identificador  text NOT NULL CHECK (tipo_identificador IN ('telefono', 'tercero')),
    telefono_cifrado    bytea,
    nombre_cifrado      bytea NOT NULL,
    referido_por        bigint REFERENCES cliente (cliente_id),
    creado_en           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT telefono_segun_tipo CHECK ((tipo_identificador = 'telefono') = (telefono_cifrado IS NOT NULL)),
    CONSTRAINT tercero_con_referente CHECK (tipo_identificador = 'telefono' OR referido_por IS NOT NULL),
    CONSTRAINT no_autorreferido CHECK (referido_por IS DISTINCT FROM cliente_id)
);

CREATE TABLE mascota (
    mascota_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    propietario_id  bigint NOT NULL REFERENCES cliente (cliente_id),
    nombre          text   NOT NULL CHECK (btrim(nombre) <> ''),
    raza            text,
    temperamento    text CHECK (temperamento IN ('tranquilo', 'nervioso', 'agresivo')),
    creado_en       timestamptz NOT NULL DEFAULT now()
);
-- «Tita» y «tita» del mismo dueño son la misma mascota.
CREATE UNIQUE INDEX mascota_unica_por_duenio ON mascota (propietario_id, lower(btrim(nombre)));

-- -----------------------------------------------------------------------------
-- 4. Cita (cabecera) — lo que se cobra UNA vez por visita vive aquí
-- -----------------------------------------------------------------------------
CREATE TABLE cita (
    cita_id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    solicitante_id           bigint NOT NULL REFERENCES cliente (cliente_id),
    origen_codigo            text   NOT NULL REFERENCES origen (codigo),
    horario_propuesto        tstzrange NOT NULL,
    estado                   estado_cita NOT NULL DEFAULT 'pendiente_aprobacion',
    version                  integer NOT NULL DEFAULT 1 CHECK (version >= 1),

    -- Servicio puerta a puerta: el traslado se cobra una vez por visita
    -- (regla de SCRUM-98), por eso está en la cabecera y no en cada mascota.
    puerta_a_puerta          boolean NOT NULL DEFAULT false,
    costo_traslado           numeric(8,2) NOT NULL DEFAULT 0 CHECK (costo_traslado >= 0),
    direccion_cifrada        bytea,
    dentro_perimetro_urbano  boolean,   -- dato NO identificante que necesita SCRUM-73 (pico y placa)

    -- Beneficio aplicado. Un obsequio en especie («le regalo el baño
    -- antipulgas») se registra con monto 0 y su detalle.
    descuento_tipo           text CHECK (descuento_tipo IN ('primera_vez', 'fidelidad', 'referido',
                                                           'multi_mascota', 'fidelidad_mensual')),  -- [tarifario v2]
    descuento_detalle        text,
    descuento_monto          numeric(8,2) NOT NULL DEFAULT 0 CHECK (descuento_monto >= 0),

    tarifario_version        text NOT NULL,          -- trazabilidad hacia tarifario_vN.json (SCRUM-98)

    -- [prototipo] Datos operativos que el agente ya registra.
    sector                   text,                    -- barrio para el costo de traslado (no la dirección)
    pedido_especial          text,                    -- pedido fuera del catálogo; el precio lo pone la propietaria
    requiere_revision_manual boolean NOT NULL DEFAULT false,
    msg_aprobacion_id        text,                    -- wamid del resumen enviado a la propietaria
    clave_idempotencia       text NOT NULL UNIQUE,   -- p. ej. wamid del mensaje que originó la propuesta
    -- Quién hizo el último cambio y con qué evidencia: lo escriben SOLO las
    -- funciones de 002 y lo copia el historial en cada evento.
    ultimo_actor             actor_cita NOT NULL DEFAULT 'agente',
    ultima_evidencia         text,
    registrado_en            timestamptz NOT NULL DEFAULT now(),
    actualizado_en           timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT horario_valido CHECK (
        NOT isempty(horario_propuesto)
        AND NOT lower_inf(horario_propuesto) AND NOT upper_inf(horario_propuesto)
        -- [prototipo] 12 h: un desenredo severo puede ocupar el día completo.
        AND upper(horario_propuesto) - lower(horario_propuesto) <= interval '12 hours'
    ),
    CONSTRAINT domicilio_coherente CHECK (
        CASE WHEN puerta_a_puerta
             THEN direccion_cifrada IS NOT NULL AND dentro_perimetro_urbano IS NOT NULL
             ELSE costo_traslado = 0 AND direccion_cifrada IS NULL
        END
    ),
    CONSTRAINT descuento_coherente CHECK (
        descuento_tipo IS NOT NULL
        OR (descuento_monto = 0 AND descuento_detalle IS NULL)
    ),
    -- Dos citas YA APROBADAS no pueden ocupar la misma franja. Las pendientes sí
    -- pueden coincidir: dos clientes pueden pedir la misma hora y la propietaria
    -- decide a cuál aprobar. SUPUESTO: la propietaria atiende una cita a la vez.
    CONSTRAINT sin_solape_aprobadas EXCLUDE USING gist (horario_propuesto WITH &&)
        WHERE (estado IN ('aprobada', 'confirmada'))
);

CREATE INDEX cita_por_estado      ON cita (estado);
CREATE INDEX cita_por_solicitante ON cita (solicitante_id);

-- -----------------------------------------------------------------------------
-- 5. Líneas de la cita: una por mascota y servicio
-- -----------------------------------------------------------------------------
-- La cotización se guarda como la entrega el motor de SCRUM-98: precio central
-- + semiamplitud de la banda de confianza + si el precio es comprometido o un
-- rango. Guardar un único número perdería justo la información con la que se
-- mide el OE5 (reducción de la variabilidad de la cotización, SCRUM-95).
CREATE TABLE cita_linea (
    cita_id                  bigint   NOT NULL REFERENCES cita (cita_id) ON DELETE CASCADE,
    linea                    smallint NOT NULL CHECK (linea >= 1),
    mascota_id               bigint   NOT NULL REFERENCES mascota (mascota_id),
    servicio_codigo          text     NOT NULL REFERENCES servicio (codigo),
    precio_estimado          numeric(8,2) NOT NULL CHECK (precio_estimado >= 0),
    semiamplitud             numeric(8,2) NOT NULL DEFAULT 0 CHECK (semiamplitud >= 0),
    es_comprometido          boolean  NOT NULL,
    atributos_no_declarados  text[]   NOT NULL DEFAULT '{}',
    desglose                 jsonb    NOT NULL DEFAULT '{}'::jsonb,  -- salida íntegra del motor
    PRIMARY KEY (cita_id, linea),
    UNIQUE (cita_id, mascota_id, servicio_codigo),
    CONSTRAINT banda_no_negativa CHECK (precio_estimado - semiamplitud >= 0)
);

-- -----------------------------------------------------------------------------
-- 6. Historial de eventos (solo inserción)
-- -----------------------------------------------------------------------------
-- Cada cambio de estado deja: quién, cuándo, desde qué versión y una FOTO de
-- la propuesta tal como estaba. Es la fuente de datos para medir tiempos de
-- aprobación y tasa de modificación en SCRUM-90/95.
CREATE TABLE cita_evento (
    evento_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cita_id          bigint NOT NULL REFERENCES cita (cita_id),
    version          integer NOT NULL,
    estado_anterior  estado_cita,                  -- NULL solo en el registro inicial
    estado_nuevo     estado_cita NOT NULL,
    actor            actor_cita  NOT NULL,
    rol_bd           text NOT NULL DEFAULT session_user,
    evidencia        text,                          -- p. ej. respuesta textual de la propietaria
    foto_propuesta   jsonb NOT NULL,
    ocurrido_en      timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX evento_por_cita ON cita_evento (cita_id, evento_id);

-- -----------------------------------------------------------------------------
-- 7. Reparto de ingresos — configuración versionada, nunca en el código
-- -----------------------------------------------------------------------------
-- No es un atributo de la cita: es una regla que se aplica a los ingresos y
-- que ya cambió una vez (20/80 → 20/70/10). Se versiona por fecha de vigencia
-- y las versiones no se editan: se agrega una nueva.
CREATE TABLE reparto_version (
    reparto_id     integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vigente_desde  date NOT NULL UNIQUE,
    nota           text
);

CREATE TABLE reparto_participacion (
    reparto_id    integer NOT NULL REFERENCES reparto_version (reparto_id),
    beneficiario  text    NOT NULL,
    porcentaje    numeric(5,2) NOT NULL CHECK (porcentaje > 0 AND porcentaje <= 100),
    PRIMARY KEY (reparto_id, beneficiario)
);

CREATE INDEX cita_por_msg_aprobacion ON cita (msg_aprobacion_id) WHERE msg_aprobacion_id IS NOT NULL;
