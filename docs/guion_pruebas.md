# Guion de pruebas del asistente (equipo)

Para probar el asistente como lo usarían clientes reales y anotar cada falla.

**Dónde se prueba:**
- **En WhatsApp**, cuando esté conectado: cada persona usa su celular.
- **Mientras tanto, en el panel → "Demo en vivo"**: una sola persona hace
  de cliente y de propietaria, con los botones de cada lado.

**Roles:**

| Rol | Quién | En WhatsApp |
|---|---|---|
| Cliente A | _______ | Su número en `NUMEROS_PERMITIDOS` |
| Cliente B | _______ | Su número en `NUMEROS_PERMITIDOS` |
| Propietaria | _______ | Su número en `PROPIETARIA_WHATSAPP`. Debe escribirle "hola" al bot al empezar el día (regla de 24 h) |

**Reglas:**
- Escribir como un cliente de verdad: con errores, sin tildes, en varios mensajes cortos.
- Si algo sale mal, **anotarlo en la hoja** (al final) y seguir con el siguiente caso.
- Cada caso nuevo empieza con un mensaje distinto, para que no se mezcle con el anterior.

---

## Bloque 1: consultas (Cliente A)

| # | Escribir | Debe pasar |
|---|---|---|
| 1.1 | `hola` (primera vez) | Llega el **aviso de privacidad** y después un saludo *(solo en WhatsApp)* |
| 1.2 | `cuanto cuesta el baño completo?` | Precios por tamaño, sin inventar; sugiere mandar una foto |
| 1.3 | `que incluye el baño premium?` | Lo que incluye según el catálogo |
| 1.4 | `cual es su horario?` | El horario configurado |
| 1.5 | `aceptan tarjeta?` | "No tengo esa información…". A la propietaria le llega "❓ Pregunta sin respuesta…" |
| 1.6 | (Propietaria) responde **deslizando** ese ❓: `si, aceptamos tarjeta` | Al cliente le llega "💬 Respuesta de la propietaria: …" |
| 1.7 | `atienden gatos?` | No debe responder con datos de perros; lo pasa a la propietaria |
| 1.8 | Nota de voz | Aviso de que solo lee texto y fotos *(solo en WhatsApp)* |

## Bloque 2: cotización por foto (Cliente B)

| # | Enviar | Debe pasar |
|---|---|---|
| 2.1 | Foto clara de un perro (de cuerpo entero) | Tamaño, tipo de pelo y rango de precio, y pregunta lo que falta |
| 2.2 | Foto borrosa o muy de lejos | Pide otra foto |
| 2.3 | Foto sin perro (un paisaje) | "No logro ver bien a su perrito" y pide otra foto |
| 2.4 | Después de 2.1: `quiero agendar` | Sigue con la reserva sin volver a preguntar el tamaño |

## Bloque 3: reservas (Cliente A)

| # | Conversación | Debe pasar |
|---|---|---|
| 3.1 | `quiero agendar un baño completo para mi shih tzu Toby` → `no tiene nudos y es tranquilo` → `lo llevo al salon` → `el sabado a las 10` | Resume la cita y dice que la propietaria la confirma. A ella le llega "🐾 Nueva cita #N por aprobar" |
| 3.2 | (Propietaria) desliza el resumen: `listo` | Al cliente le llega la confirmación con fecha, servicio y total |
| 3.3 | `quiero agendar para mi perrita, es mestiza` | Pregunta **primero el tamaño** y luego el tipo de pelo |
| 3.4 | Puerta a puerta: `que la recojan en mi casa, vivo en el Condado` y luego `el jueves a las 5 de la tarde` | Jueves de 16:00 a 20:00 hay pico y placa: ofrece otros horarios |
| 3.5 | `tengo 2 perritos, un pug y un golden` | Cotiza los dos y arma una sola cita |
| 3.6 | `mi perro es agresivo` | Rechazo amable, sin agendar |
| 3.7 | `pesa 50 kilos` | Rechazo amable (más de 45 kg) |
| 3.8 | `que horarios tiene el miercoles?` → `en la tarde` → `despues de las 3` | Ofrece horarios de ese día, de la tarde y después de las 15:00 |
| 3.9 | `puedes hacerle el baño sin el accesorio?` → `cuanto me saldria asi?` | Anota el pedido especial y **no da precio**: dice que lo valida la propietaria |

## Bloque 4: la propietaria decide (Propietaria + Cliente B)

Primero, Cliente B arma una reserva como en el 3.1.

| # | Propietaria escribe (deslizando el resumen) | Debe pasar |
|---|---|---|
| 4.1 | `a las 12 esta bien` | El cliente recibe la **propuesta** del nuevo horario; la cita **no** queda confirmada todavía |
| 4.2 | (Cliente) `si perfecto` | Queda confirmada y la propietaria recibe "✅ El cliente aceptó…" |
| 4.3 | Otra reserva → `no` | El cliente recibe otros horarios para elegir |
| 4.4 | Otra reserva → `cobrale 20` | Propuesta al cliente con el total de 20 $ |
| 4.5 | (Cliente, con cita confirmada) `disculpa a esa hora ya no puedo` | Le ofrece reprogramar, **no** abre una reserva nueva |
| 4.6 | (Cliente) `quiero cancelar mi cita` | Cancela y le avisa a la propietaria |

## Bloque 5: comandos de la propietaria

| # | Escribir | Debe pasar |
|---|---|---|
| 5.1 | `pendientes` | Lista de las citas por aprobar |
| 5.2 | `listo #N` (sin deslizar) | Aprueba la cita N |
| 5.3 | `cobré 22 a la cita #N` | "💰 registré 22.00$ cobrado…". En el panel, la desviación cotizado vs cobrado |
| 5.4 | `por cobrar` | Citas atendidas sin el cobro registrado |
| 5.5 | `pausar bot` → (Cliente) `hola` → (Propietaria) desliza y responde | El bot no contesta al cliente. Ella recibe el mensaje y su respuesta le llega al cliente |
| 5.6 | `activar bot` | El bot vuelve a responder |
| 5.7 | Dejar una cita sin responder 45 min *(solo en WhatsApp)* | Llega "⏰ Recordatorio 1…" |

## Al final del día

Revisar el panel:
- **Citas:** ¿están las que se crearon?
- **Mensajes no entregados:** ¿hay alguno?
- **Estado del sistema:** ¿algo en rojo?

---

## Hoja de registro de fallas

Copiarla en una hoja de cálculo compartida. Una fila por falla:

| Fecha y hora | Quién | Caso (#) | Qué escribió | Qué esperaba | Qué pasó | Captura |
|---|---|---|---|---|---|---|
| | | | | | | |

Pasarle la hoja a Claude. Cada falla se corrige con su prueba automática y queda
en el [registro de errores](../evaluacion/registro_errores.md) (SCRUM-91). El
porcentaje de casos que pasan alimenta SCRUM-89, con meta ≥ 85 %.
