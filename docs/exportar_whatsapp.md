# Cómo exportar las conversaciones de WhatsApp Business

Instrucciones para la propietaria. Toma unos 15–20 minutos.

**Para qué las usamos:**
1. Medir cuánto tarda hoy en responder y en confirmar una cita, para compararlo con el asistente.
2. Ver cuánto cambia el precio entre lo que se cotiza y lo que se cobra.
3. Probar el asistente con mensajes reales de clientes.

**Privacidad:**
- Los archivos se guardan solo en el computador del equipo, nunca en internet ni en el repositorio.
- Los nombres y números se reemplazan por códigos antes de analizarlos.
- En el informe solo aparecen cifras (por ejemplo, "responde en 25 minutos en promedio"), nunca mensajes ni nombres.
- Al terminar el proyecto, los archivos se borran.

## Qué chats exportar

- Chats con **clientes del servicio de grooming** de los **últimos 3 a 6 meses**, sobre todo los que pidieron o agendaron una cita.
- Unos **30 a 50 chats** alcanzan. No hace falta exportar todos.
- **No** exportar chats personales, de familia, de proveedores ni de grupos.

## Paso a paso

WhatsApp exporta **un chat a la vez**. Para cada chat:

### En Android

1. Abrir el chat del cliente.
2. Tocar **⋮** (tres puntos, arriba a la derecha) → **Más** → **Exportar chat**.
3. Elegir **SIN ARCHIVOS**: no hacen falta fotos ni audios, y el archivo pesa mucho menos.
4. En "Compartir con", elegir **Drive** y guardarlo en una carpeta llamada `Chats Lina's Pet`.

### En iPhone

1. Abrir el chat del cliente.
2. Tocar el **nombre del cliente** (arriba) → bajar hasta **Exportar chat**.
3. Elegir **Sin archivos**.
4. Guardarlo en **Archivos** o en **Drive**, en la carpeta `Chats Lina's Pet`.

Cada chat se guarda como un archivo `.txt` (en iPhone puede venir dentro de un `.zip`, y está bien así).

## Cómo entregarlos

- Compartir la carpeta de Drive **solo** con el correo de quien la recibe del equipo, con permiso de **lector**.
- No enviarlos por WhatsApp ni por correo masivo.

## Antes de exportar

- Si el teléfono está en español, la fecha sale como día/mes/año, que es lo que esperamos.
- No hace falta editar ni borrar nada de los chats: la anonimización la hacemos nosotros.

---

## Para el equipo (no es para la propietaria)

1. Descargar los `.txt` en `datos_crudos/chats/` (excluida del repositorio). Si vienen en `.zip`, descomprimirlos ahí.
2. **Línea base** (usa la hora de cada mensaje):
   ```
   python -m evaluacion.linea_base.linea_base_whatsapp --exports datos_crudos/chats --propietaria "<nombre con el que aparece ella>"
   ```
3. **Corpus real para el NLU** (seudonimizado):
   ```
   export MIA_SALT="<secreto, una sola vez>"
   python datasets/nlu/anonimizador.py --entrada datos_crudos/chats/<chat>.txt --salida corpus_anonimizado.csv --propietaria "<nombre>"
   ```
   Después: revisión manual del 100 %, anotación con la guía y `build_dataset.py --corpus-real`.
4. Al cierre del proyecto: borrar `datos_crudos/` y destruir la sal (protocolo de SCRUM-63).
