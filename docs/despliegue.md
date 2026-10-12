# Despliegue en Railway: entornos de pruebas y piloto (SCRUM-92)

Hay dos copias del sistema que no comparten nada: **pruebas**, para el equipo,
y **piloto**, para la propietaria y los clientes reales. Así una cita de prueba
nunca le llega a un cliente ni aparece en el calendario del negocio.

| | pruebas | piloto |
|---|---|---|
| Rama | `prototipo-s4` | `main` (solo lo ya probado) |
| `MIA_MODO` | `pruebas`: solo responde a `NUMEROS_PERMITIDOS` | `produccion`: atiende a todos |
| Propietaria | un integrante del equipo | la propietaria |
| Base de datos | volumen propio | otro volumen |
| WhatsApp | número de prueba de Meta (app "pruebas") | número del negocio (app "piloto") |
| Calendario | "Lina's Pet Salón (pruebas)" | el del negocio |
| Gemini | clave con límite de gasto bajo | clave propia, para medir el costo real |
| Variables | [deploy/pruebas.env.example](../deploy/pruebas.env.example) | [deploy/piloto.env.example](../deploy/piloto.env.example) |

`railway.json` ya define el comando de arranque, el chequeo de salud (`/`) y
el reinicio automático. Python se fija con `.python-version`.

---

## Fase 1 — Pruebas sin WhatsApp (se puede hacer hoy)

Sin los tokens de Meta, el sistema ya funciona en el **panel**: la pestaña
"Demo en vivo" corre el mismo orquestador que WhatsApp (NLU, RAG, foto,
agenda, aprobación) y sirve para la demo con el tutor.

1. En [railway.com](https://railway.com): **New Project → Deploy from GitHub
   repo → Proyecto-MIA**.
2. En el servicio: **Settings → Source → Branch** = `prototipo-s4`.
3. **Settings → Networking → Generate Domain** (queda `https://<app>.up.railway.app`).
4. Clic derecho en el servicio → **Attach volume**, *mount path* `/data`.
5. **Variables → Raw Editor**, como mínimo:
   ```
   MIA_MODO=pruebas
   GEMINI_API_KEY=...
   MIA_DB_PATH=/data/mia.sqlite3
   DEMO_CLAVE=<clave larga>
   ```
6. Esperar el despliegue y abrir `https://<app>.up.railway.app/panel?clave=<DEMO_CLAVE>`.
7. Revisar la pestaña **"Estado del sistema"**: WhatsApp aparecerá en rojo (todavía no hay
   tokens); el resto debe estar en verde o en aviso.
8. Renombrar el entorno: **Project Settings → Environments**: `production` → `pruebas`.

**Costo:** cada mensaje en la demo llama a Gemini, igual que en WhatsApp.

## Fase 2 — Pruebas con WhatsApp (cuando lleguen los tokens)

1. En [developers.facebook.com](https://developers.facebook.com): app de tipo
   **Negocios** "Lina's Pet - pruebas" → agregar **WhatsApp**.
2. **WhatsApp → Configuración de la API**: anotar el *Phone number ID* del
   número de prueba y agregar como destinatarios los números del equipo (máximo 5).
   Cada uno debe confirmar el código que le llega.
3. **Token permanente:** Business Settings → Usuarios del sistema → crear uno
   (Admin) → asignarle la app y la cuenta de WhatsApp → **Generar token** con
   `whatsapp_business_messaging` y `whatsapp_business_management`, sin vencimiento.
   El token temporal de la consola vence en 24 h.
4. En Railway, agregar `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
   `WHATSAPP_VERIFY_TOKEN` (una cadena inventada), `NUMEROS_PERMITIDOS` y
   `PROPIETARIA_WHATSAPP`.
5. Meta → **WhatsApp → Configuración → Webhook**:
   - URL: `https://<app>.up.railway.app/webhook`
   - Token de verificación: el mismo `WHATSAPP_VERIFY_TOKEN`
   - **Suscribir el campo `messages`** (si no, no llega nada).
6. Prueba: desde un número del equipo escribir "hola" al número de prueba.
   - Debe llegar primero el aviso de privacidad y luego la respuesta.
   - Si no responde: ver **Deploy Logs** en Railway y "Estado del sistema" en el panel.
7. Quien hace de propietaria debe escribirle al bot al empezar cada día de pruebas
   (regla de 24 h), hasta que las plantillas estén aprobadas.

## Fase 3 — Piloto (con la propietaria, S7-S8)

**Antes de empezar:**
- La propietaria validó el contenido y los precios (`app/rag/ESQUEMA_CONTENIDO.md`, sección 5).
- Las plantillas de Meta están aprobadas ([plantillas_meta.md](plantillas_meta.md)).
- Se acordó el texto del aviso de privacidad (`config_agenda.json` → `aviso_privacidad`).
- La propietaria recibió la [guía](guia_propietaria.md).

**Pasos:**
1. Mezclar `prototipo-s4` en `main`.
2. Railway → **Project Settings → Environments → New Environment** "piloto"
   (duplicando "pruebas"). En el entorno piloto:
   - **Settings → Source → Branch** = `main`;
   - **volumen nuevo** en `/data`. Comprobar que no sea el de pruebas;
   - variables de [deploy/piloto.env.example](../deploy/piloto.env.example), con `MIA_MODO=produccion`;
   - **otro dominio**.
3. Meta: **otra app** "Lina's Pet - piloto" con el número del negocio. El
   webhook se configura por app, así que con dos apps cada entorno recibe solo
   lo suyo. Registrar en ella las plantillas.

   ⚠️ Un número usado con la API ya no se puede usar en la app WhatsApp
   Business del teléfono. Acordarlo con la propietaria antes de migrarlo.
4. Google Calendar: calendario **del negocio** compartido con la cuenta de servicio.
5. Verificar "Estado del sistema" en verde.
6. Prueba de punta a punta con un número del equipo:
   - cotizar → agendar → aprobar → "cobré X a la cita #N";
   - "pausar bot" / "activar bot".

**Contingencia:** si algo falla, la propietaria escribe **"pausar bot"** y
atiende ella: cada mensaje le llega y su respuesta, citando el mensaje, vuelve
al cliente.

## Promover cambios de pruebas a piloto

1. Probar en `prototipo-s4` (entorno pruebas).
2. `git checkout main && git merge prototipo-s4 && git push`.
3. El entorno piloto se redespliega solo.

Nunca se edita `main` directamente.
