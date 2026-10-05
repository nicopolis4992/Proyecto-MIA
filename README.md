# Lina's Pet Salón - Asistente WhatsApp (Proyecto MIA)

Backend del sistema multiagente conversacional para automatizar atención,
cotización y agendamiento de citas de grooming, vía WhatsApp Business Cloud API.

## Estado actual

- [x] Estructura base del repo
- [x] Servidor FastAPI mínimo (`GET /`, `GET /webhook` para verificación de Meta)
- [x] `POST /webhook` para recibir mensajes reales (SCRUM-83)
- [x] Envío de mensajes salientes (SCRUM-84)
- [x] Primer nodo de LangGraph + Gemini (SCRUM-85)
- [ ] Conectar con la app real de WhatsApp Business en Meta (bloqueado por verificación de cuenta, en progreso)

## Cómo correrlo localmente

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# completa WHATSAPP_VERIFY_TOKEN con cualquier string que tú definas

uvicorn app.main:app --reload --port 8000
```

Prueba local de verificación (simula lo que hace Meta):

```bash
curl "http://localhost:8000/webhook?hub.mode=subscribe&hub.verify_token=TU_TOKEN&hub.challenge=1234"
```

Debe devolver `1234`. Si devuelve 403, revisa que `WHATSAPP_VERIFY_TOKEN`
en tu `.env` coincida exactamente con lo que mandaste en el `curl`.

## Probar el ciclo completo en local (sin WhatsApp real)

Con `GEMINI_API_KEY` configurada en tu `.env`, puedes simular un mensaje
entrante de WhatsApp sin depender de Meta:

```bash
curl -X POST http://localhost:8000/webhook `
  -H "Content-Type: application/json" `
  -d '{\"entry\":[{\"changes\":[{\"value\":{\"messages\":[{\"from\":\"593999999999\",\"type\":\"text\",\"text\":{\"body\":\"Hola, cuanto cuesta el bano para un perro grande?\"}}]}}]}]}'
```

(En PowerShell, si las comillas dan problemas, usa `Invoke-RestMethod` con
un objeto convertido a JSON en vez de un string a mano.)

Como todavía no hay `WHATSAPP_ACCESS_TOKEN` real, vas a ver en la consola
del servidor un error al intentar *enviar* la respuesta (eso es esperado),
pero confirma que Gemini sí generó una respuesta antes de fallar el envío.

## Siguiente paso

1. Desplegar esto a Railway. ✅ Ya hecho.
2. Crear la app en Meta for Developers, agregar el producto WhatsApp.
   **Bloqueado actualmente**: la verificación de cuenta de desarrollador
   no está enviando el código de confirmación. Mientras se resuelve,
   el resto del sistema (webhook, orquestador, envío) ya está listo
   para conectarse en cuanto Meta lo permita.
3. En la configuración del webhook de la app de Meta, pegar la URL de
   Railway (`https://tu-app.up.railway.app/webhook`) y el mismo
   `WHATSAPP_VERIFY_TOKEN` que pusiste en tu `.env` y en Railway.
4. Meta hará el `GET /webhook` de verificación automáticamente al guardar.
5. Agregar `WHATSAPP_ACCESS_TOKEN` y `WHATSAPP_PHONE_NUMBER_ID` reales
   (los da Meta al configurar el producto WhatsApp) tanto en tu `.env`
   local como en las Variables de Railway.

## Piloto interno (modo pruebas) y paso a producción

Por defecto el bot corre en `MIA_MODO=pruebas`: solo responde a los números de
`NUMEROS_PERMITIDOS` y a `PROPIETARIA_WHATSAPP`, que en esta fase es el teléfono
de un integrante del equipo haciendo de propietaria. Cualquier otro número se
ignora, así que ningún cliente real recibe mensajes.

Sin WhatsApp, `python simulador.py --guion` corre el mismo flujo en consola.

Checklist para pasar a clientes reales:
1. La propietaria valida precios (`tarifario_v1.json`), contenido del RAG
   (`app/rag/conocimiento/`) y horario (`app/agenda/config_agenda.json`).
2. Re-indexar: `python -m app.rag.indexador`.
3. En Railway: `PROPIETARIA_WHATSAPP` = número real de la propietaria y
   `MIA_MODO=produccion`.
4. Verificar en `GET /` que responde `"modo": "produccion"`.

## Panel web (demo + agenda + dashboard de la propietaria)

```bash
uvicorn app.main:app --reload --port 8000
# abrir http://localhost:8000/panel
```

- **Panel de la dueña:** ingresos estimados, citas confirmadas y por aprobar,
  tiempo hasta confirmar, % de cotizaciones con precio exacto, servicios más
  pedidos, próximas citas y detalle de cada cita con su trazabilidad.
- **Agenda:** vista semanal de las citas por estado.
- **Demo en vivo:** chat de la clienta y de la propietaria con el mismo
  sistema que atiende WhatsApp (Gemini real), sin enviar nada a Meta.
  "Cargar datos de ejemplo" crea citas **simuladas** para ver el panel lleno.

Para abrirlo en Railway define `DEMO_CLAVE` y entra con `https://<app>/panel?clave=<DEMO_CLAVE>`.

## Google Calendar (citas aprobadas → calendario)

1. En [console.cloud.google.com](https://console.cloud.google.com): crear un proyecto,
   habilitar **Google Calendar API**, crear una **cuenta de servicio** y descargar su clave JSON.
2. En Google Calendar: crear el calendario "Lina's Pet Salón (pruebas)", y en
   *Compartir con personas* agregar el correo de la cuenta de servicio con
   permiso **Hacer cambios en eventos**. Copiar el *ID del calendario*.
3. Variables: `GOOGLE_CALENDAR_ID` y `GOOGLE_SERVICE_ACCOUNT_JSON` (o `_FILE` en local).
4. Al aprobar una cita (WhatsApp o demo), aparece en el calendario y la
   disponibilidad consulta los horarios ocupados.
