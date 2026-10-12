# Plantillas de WhatsApp para registrar en Meta (SCRUM-92)

WhatsApp solo permite escribirle a alguien con texto libre durante las **24 h**
siguientes a su último mensaje. Fuera de esa ventana, la única opción es una
**plantilla aprobada por Meta** (si no, Meta responde con el error 131047).

**Cómo las usa el sistema** (`app/mensajeria.py`):
1. Envía la plantilla con un resumen de una línea de lo que quería decir.
2. Guarda el mensaje completo "en espera".
3. Cuando la persona responde, aunque sea "ver", se abre la ventana y le llega
   el mensaje completo.
4. Si la propietaria responde "listo" citando la plantilla, la cita se aprueba igual.

## Dónde registrarlas

Meta Business Suite → **Administrador de WhatsApp → Plantillas de mensajes →
Crear plantilla**.

## Plantilla 1: `aviso_propietaria`

- **Categoría:** Utilidad
- **Idioma:** Español (`es`)
- **Cuerpo:**
  ```
  Tienes una novedad en el asistente de Lina's Pet Salón: {{1}}. Responde *ver* para recibir el detalle completo.
  ```
- **Ejemplo para {{1}}:** `Nueva cita #7 por aprobar · Cliente: Rosa · Luna: Baño Completo`
- **Se usa para:** solicitudes de aprobación, recordatorios, preguntas de
  clientes que el bot no supo responder y avisos de citas vencidas.

## Plantilla 2: `aviso_cliente`

- **Categoría:** Utilidad
- **Idioma:** Español (`es`)
- **Cuerpo:**
  ```
  Hola, tiene una actualización sobre su cita en Lina's Pet Salón: {{1}}. Responda *ver* para recibir el detalle.
  ```
- **Ejemplo para {{1}}:** `¡Listo! Queda agendado Toby para el jueves 15 de octubre a las 10:00`
- **Se usa para:** la confirmación de la cita, el cambio de horario o precio
  propuesto por la propietaria y la respuesta de la propietaria a una pregunta.

## Reglas de Meta que estas plantillas ya cumplen

- La variable no está ni al inicio ni al final del texto.
- El parámetro se envía en una sola línea, sin tabulaciones ni espacios
  repetidos (`resumen_corto`), con un máximo de 160 caracteres.
- Son de categoría Utilidad: informan sobre una transacción que el usuario
  inició, sin contenido promocional.

## Después de la aprobación

En Railway, en el entorno que corresponda:
```
WHATSAPP_PLANTILLA_PROPIETARIA=aviso_propietaria
WHATSAPP_PLANTILLA_CLIENTE=aviso_cliente
```
"Estado del sistema" en el panel muestra si están configuradas.

**Para tener en cuenta:**
- La aprobación suele tardar de minutos a 1–2 días.
- Si la rechazan, ajustar la redacción y volver a enviarla.
- El número de prueba de Meta trae la plantilla `hello_world` ya aprobada. Las
  nuevas se crean en la cuenta de WhatsApp Business de cada app.
