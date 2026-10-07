-- =============================================================================
-- Proyecto MIA · Usuarios de conexión (NO es una migración: se ejecuta a mano)
--
-- Un usuario por servicio, cada uno miembro de UN rol. Las contraseñas no se
-- versionan: reemplace los marcadores en el SQL Editor de Supabase y guarde
-- las cadenas de conexión como variables de entorno en Railway.
--
--   Servicio que lo usa                     Usuario           Variable de entorno
--   agente conversacional (webhook)         mia_srv_agente    MIA_DSN_AGENTE
--   canal de la propietaria (aprobaciones)  mia_srv_aprob     MIA_DSN_APROBACION
--   tareas automáticas (reintentos, purga)  mia_srv_sistema   MIA_DSN_SISTEMA
--   panel y métricas (solo lectura)         mia_srv_lectura   MIA_DSN_LECTURA
--
-- Conexión desde Railway: use el «Session pooler» de Supavisor (IPv4). La
-- conexión directa de Supabase es solo IPv6. En el pooler el usuario se escribe
-- como  <usuario>.<project-ref>.
-- =============================================================================
CREATE ROLE mia_srv_agente  LOGIN PASSWORD '<<CAMBIAR-agente>>'  IN ROLE mia_agente;
CREATE ROLE mia_srv_aprob   LOGIN PASSWORD '<<CAMBIAR-aprob>>'   IN ROLE mia_aprobacion;
CREATE ROLE mia_srv_sistema LOGIN PASSWORD '<<CAMBIAR-sistema>>' IN ROLE mia_sistema;
CREATE ROLE mia_srv_lectura LOGIN PASSWORD '<<CAMBIAR-lectura>>' IN ROLE mia_lectura;

-- Búsqueda por defecto, para no tener que calificar cada objeto.
ALTER ROLE mia_srv_agente  SET search_path = mia, mia_op, mia_rv;
ALTER ROLE mia_srv_aprob   SET search_path = mia, mia_op;
ALTER ROLE mia_srv_sistema SET search_path = mia, mia_op, mia_rv;
ALTER ROLE mia_srv_lectura SET search_path = mia;
