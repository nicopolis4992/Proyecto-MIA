-- SCRUM-73 · Migración 6/7: parámetros de la restricción vehicular (DMQ)
-- Proyecto MIA — Lina's Pet Salón · PostgreSQL 16
-- Los valores de la regla viven aquí, no en el código. Se versionan por vigencia
-- (mismo criterio que la configuración de reparto de SCRUM-74, D8).

SET ROLE mia_duenio;   -- el esquema lo crea la migración 1

-- Una versión de la regla municipal por período de vigencia.
CREATE TABLE mia_rv.version_regla (
    id                   text PRIMARY KEY,
    vigente_desde        date NOT NULL,
    vigente_hasta        date,                          -- NULL = vigente sin fecha de término
    fuente               text NOT NULL,                 -- de dónde sale el dato (trazabilidad)
    aplica_fines_semana  boolean NOT NULL DEFAULT false,
    registrado_en        timestamptz NOT NULL DEFAULT now(),
    CHECK (vigente_hasta IS NULL OR vigente_hasta > vigente_desde),
    -- Dos versiones no pueden regir el mismo día.
    EXCLUDE USING gist ((daterange(vigente_desde, vigente_hasta, '[)')) WITH &&)
);

-- Franjas horarias restringidas de cada versión, intervalo [inicio, fin).
CREATE TABLE mia_rv.franja (
    version_id  text NOT NULL REFERENCES mia_rv.version_regla(id) ON DELETE CASCADE,
    inicio      time NOT NULL,
    fin         time NOT NULL,
    CHECK (fin > inicio),
    PRIMARY KEY (version_id, inicio)
);

-- Qué día de la semana (ISO: 1 = lunes) se restringe cada último dígito de placa.
CREATE TABLE mia_rv.digito_dia (
    version_id  text NOT NULL REFERENCES mia_rv.version_regla(id) ON DELETE CASCADE,
    digito      smallint NOT NULL CHECK (digito BETWEEN 0 AND 9),
    dia_iso     smallint NOT NULL CHECK (dia_iso BETWEEN 1 AND 7),
    PRIMARY KEY (version_id, digito)                   -- un dígito, un solo día
);

-- Feriados, puentes y suspensiones extraordinarias dispuestas por la AMT.
CREATE TABLE mia_rv.dia_sin_restriccion (
    fecha       date PRIMARY KEY,
    tipo        text NOT NULL CHECK (tipo IN ('feriado_nacional', 'feriado_local', 'puente', 'suspension_extraordinaria')),
    motivo      text NOT NULL,
    verificado  boolean NOT NULL DEFAULT false,
    registrado_en timestamptz NOT NULL DEFAULT now()
);

-- Parámetros operativos del negocio (vehículo, traslados, horario).
CREATE TABLE mia_rv.parametro_operacion (
    clave          text PRIMARY KEY,
    valor          jsonb NOT NULL,
    nota           text,
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

-- Permisos: el agente solo LEE la regla; la edita el rol administrador del negocio.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mia_agente') THEN
        GRANT USAGE ON SCHEMA mia_rv TO mia_agente;
        GRANT SELECT ON ALL TABLES IN SCHEMA mia_rv TO mia_agente;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mia_sistema') THEN
        GRANT USAGE ON SCHEMA mia_rv TO mia_sistema;
        GRANT SELECT ON ALL TABLES IN SCHEMA mia_rv TO mia_sistema;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Datos iniciales
-- ---------------------------------------------------------------------------
-- SCRUM-73 · Datos iniciales (parte de la migración 6/7). Deben coincidir con config/restriccion_vehicular.json
-- (la prueba CA12 verifica que ambas fuentes producen la misma configuración).

INSERT INTO mia_rv.version_regla (id, vigente_desde, vigente_hasta, fuente, aplica_fines_semana) VALUES
('DMQ-2026', '2026-01-01', NULL,
 'AMT, según prensa del 24/09/2026 y 01/10/2026 (El Comercio, Extra): jueves placas 7 y 8; 06h00-09h30 y 16h00-20h00. La franja vespertina era 16h00-21h00 hasta abril de 2023 (Quito Informa).',
 false);

INSERT INTO mia_rv.franja (version_id, inicio, fin) VALUES
('DMQ-2026', '06:00', '09:30'),
('DMQ-2026', '16:00', '20:00');

INSERT INTO mia_rv.digito_dia (version_id, digito, dia_iso) VALUES
('DMQ-2026', 1, 1), ('DMQ-2026', 2, 1),
('DMQ-2026', 3, 2), ('DMQ-2026', 4, 2),
('DMQ-2026', 5, 3), ('DMQ-2026', 6, 3),
('DMQ-2026', 7, 4), ('DMQ-2026', 8, 4),
('DMQ-2026', 9, 5), ('DMQ-2026', 0, 5);

INSERT INTO mia_rv.dia_sin_restriccion (fecha, tipo, motivo, verificado) VALUES
('2026-01-01', 'feriado_nacional', 'Año Nuevo', true),
('2026-01-02', 'puente', 'Puente de Año Nuevo (descanso 1-4 ene)', false),
('2026-02-16', 'feriado_nacional', 'Carnaval', true),
('2026-02-17', 'feriado_nacional', 'Carnaval', true),
('2026-04-03', 'feriado_nacional', 'Viernes Santo', true),
('2026-05-01', 'feriado_nacional', 'Día del Trabajo', true),
('2026-05-25', 'feriado_nacional', 'Batalla de Pichincha (trasladado)', true),
('2026-06-26', 'suspension_extraordinaria', 'Feriado decretado tras la victoria de Ecuador en el Mundial; la AMT suspendió el pico y placa todo el día', true),
('2026-08-10', 'feriado_nacional', 'Primer Grito de Independencia', true),
('2026-10-09', 'feriado_nacional', 'Independencia de Guayaquil', true),
('2026-11-02', 'feriado_nacional', 'Día de Difuntos', true),
('2026-11-03', 'feriado_nacional', 'Independencia de Cuenca', true),
('2026-12-25', 'feriado_nacional', 'Navidad', true);

INSERT INTO mia_rv.parametro_operacion (clave, valor, nota) VALUES
('ultimo_digito_placa', '7', 'Jueves (7 u 8). Falta el dígito exacto; con la tabla vigente ambos dan el mismo resultado.'),
('ultimo_digito_placa_confirmado', 'false', NULL),
('vehiculo_exento', 'false', NULL),
('salon_dentro_perimetro', 'true', 'Supuesto conservador: falta confirmar el sector del local.'),
('salon_dentro_perimetro_confirmado', 'false', NULL),
('minutos_traslado', '30', 'Provisional, por trayecto.'),
('minutos_traslado_confirmado', 'false', NULL),
('margen_seguridad_min', '10', NULL),
('horario_atencion', '["08:00", "18:00"]', 'Provisional.'),
('horario_atencion_confirmado', 'false', NULL),
('paso_busqueda_min', '15', NULL);
