# Base de datos en Supabase (SCRUM-74 + SCRUM-73)

Esquema relacional que reemplaza al SQLite provisional de `app/persistencia/repositorio.py`. Parte del diseño de SCRUM-74, con su regla central: **la aprobación humana se garantiza en la base de datos, no en el prompt**. Se adaptó al flujo que ya implementa el prototipo y a las restricciones de Supabase.

## Contenido

```
supabase/migrations/   7 migraciones, en orden (compatibles con `supabase db push`)
  …120000_mia_base.sql                 extensiones, roles y esquemas
  …120100_mia_citas.sql                tablas de la cita (SCRUM-74 + flujo del prototipo)
  …120200_mia_reglas.sql               máquina de estados, historial, funciones, vistas
  …120300_mia_catalogos.sql            servicios, orígenes, transiciones, reparto
  …120400_mia_operacion.sql            sesiones, cola de salida, deduplicación (mia_op)
  …120500_mia_restriccion_vehicular.sql  parámetros de SCRUM-73 (mia_rv)
  …120600_mia_seguridad_supabase.sql   RLS y revocaciones para anon/authenticated
supabase/usuarios_login.sql  usuarios de conexión (a mano, sin contraseñas en el repo)
mia_agenda/            registrar_cita_propuesta(), seudonimización y cifrado (SCRUM-74)
tests/                 65 pruebas contra PostgreSQL real que emula Supabase
```

## Cómo aplicarlo

1. Con la CLI, desde la carpeta `db/`: `supabase link --project-ref <ref>` y luego `supabase db push` (lee `supabase/migrations/`). Sin la CLI, se pegan los 7 archivos en orden en el SQL Editor.
2. Se ejecuta `supabase/usuarios_login.sql` en el SQL Editor, después de cambiar las contraseñas.
3. En Railway se configuran `MIA_DSN_AGENTE`, `MIA_DSN_APROBACION`, `MIA_DSN_SISTEMA` y `MIA_DSN_LECTURA` con el **Session pooler** (IPv4, puerto 5432, usuario `<rol>.<project-ref>`). La conexión directa de Supabase es solo IPv6. El *Transaction pooler* (6543) no admite sentencias preparadas.
4. Se configuran `MIA_CLAVE_SEUDONIMO_OPERACION` y `MIA_CLAVES_CIFRADO` (ver SCRUM-74). Ninguna de las dos va a Supabase: la base nunca ve las claves.

Los esquemas `mia`, `mia_op` y `mia_rv` **no se agregan** a «Exposed schemas» de la API: la aplicación usa PostgreSQL directo. Aun así, la migración 7 activa RLS y revoca todo a `anon` y `authenticated`, por si alguien los expone por error.

## Qué cambió respecto de SCRUM-74

| Cambio | Por qué |
|---|---|
| Estados `propuesta_cliente`, `en_reprogramacion` y `cancelada`; actor `cliente` | Son los que ya usa el prototipo (`app/agenda/`) |
| `fn_proponer_al_cliente` (rol aprobación) | La propietaria cambia hora o precio y se lo propone al cliente. Su cambio cuenta como su aprobación |
| El agente puede pasar `propuesta_cliente → aprobada` | El cliente acepta lo que **la propietaria** propuso. El agente sigue sin poder aprobar algo que ella no vio (prueba SB5) |
| `fn_reprogramar` (rol agente) | El nuevo horario vuelve a la propietaria como versión nueva |
| Servicios del tarifario v2 (`express` … `deslanado`) junto a las siglas del Excel | La equivalencia entre ambos sigue pendiente (H2) |
| Descuentos `multi_mascota` y `fidelidad_mensual` | Tarifario v2 |
| Columnas `sector`, `pedido_especial`, `requiere_revision_manual` y `msg_aprobacion_id` | Datos que el prototipo ya registra |
| Duración máxima de 12 h (antes 8) | Un desenredo severo ocupa el día completo |
| Esquemas `mia_op` y `mia_rv` | Estado operativo del prototipo y parámetros de SCRUM-73 |

## De SQLite a Supabase: equivalencias

| SQLite (`repositorio.py`) | Supabase | Diferencia que debe manejar el adaptador |
|---|---|---|
| `citas` | `mia.cita` + `mia.cita_linea` | El teléfono y el nombre van cifrados. Cada mascota es una línea. Los cambios de estado pasan **solo** por funciones (`fn_cambiar_estado`, `fn_proponer_al_cliente`, `fn_reprogramar`), nunca por `UPDATE` |
| `citas.ciclo_aprobacion` | `mia.cita.version` | Cada transición exige la versión que se tiene a la vista |
| `citas.total_acordado` | se calcula en `mia.v_cita_resumen` | La propietaria ajusta el precio de las líneas con `fn_proponer_al_cliente` |
| `eventos_cita` | `mia.cita_evento` | Lo escribe la base sola en cada cambio de estado, con una foto de la propuesta |
| `sesiones` | `mia_op.sesion` | La clave es el HMAC del teléfono, no el número |
| `mensajes_salientes` | `mia_op.mensaje_saliente` | El destino y el cuerpo van cifrados (Fernet) |
| `mensajes_procesados` | `mia_op.mensaje_procesado` | Igual; se purga con `mia_op.fn_purgar_operacion()` |

**Lo que falta** es un `RepositorioSupabase` con la misma interfaz pública que `Repositorio`, para que los agentes no noten el cambio. Ese adaptador debe abrir **una conexión por rol**: el webhook del cliente con `MIA_DSN_AGENTE` y el canal de la propietaria con `MIA_DSN_APROBACION`. Si todo usa una sola conexión, se pierde la garantía de la aprobación humana.

## Pruebas

```bash
pip install -r db/requirements-db.txt
export MIA_PG_ADMIN_DSN="host=localhost port=5432 user=postgres dbname=postgres"   # clúster solo para pruebas
python -m pytest db/tests -q
```

El entorno de prueba ejecuta las migraciones con un usuario **sin superusuario** (con CREATEROLE, CREATEDB y BYPASSRLS, como el `postgres` de Supabase) y crea los roles `anon`, `authenticated` y `service_role`. Resultado al 06/10/2026: **65 pruebas en verde**, entre ellas las 35 originales de SCRUM-74 sin cambios. Sin `MIA_PG_ADMIN_DSN`, las pruebas se omiten y no rompen el resto del repositorio.
