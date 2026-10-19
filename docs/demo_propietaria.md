# Guion de la demo para la propietaria (reunión virtual, ~10 min)

Se comparte pantalla con el **panel en línea → pestaña "Demo en vivo"**. Ahí corre el
mismo asistente que atenderá WhatsApp: a la izquierda escribe la **clienta** y a la
derecha la **propietaria**. Es una base aparte: **nada llega a clientes reales**.
Cada mensaje gasta unos centavos de Gemini.

## Antes de la reunión (15 min)

1. **Entrar sin mostrar la clave:** abrir `https://linaspetsalon.up.railway.app/panel` (sin
   `?clave=`), escribir la clave cuando la pida y comprobar que carga. Queda guardada en el
   navegador, así que al compartir pantalla la barra de direcciones no muestra la clave.
2. Botón **Reiniciar demo** (barra superior), para empezar con la cita #1. Después, pestaña **Demo en vivo**.
3. Tener a mano **una foto de un perro de cuerpo entero** (del álbum del salón, por ejemplo
   `READ/para_colab/dataset/imagenes/`).
4. Navegador con **zoom al 125 %**, para que se lea bien al compartir. Cerrar las demás pestañas.
5. **Ensayar el guion una vez completo.** Si algo responde distinto, mejor descubrirlo antes.
6. Tener abierta la [guía de una página](guia_propietaria.md) para compartirla al final.

## La demo

Cada mensaje se escribe en el chat de la izquierda (clienta) o de la derecha (propietaria).
Los botones de respuesta rápida debajo de cada chat traen varios de estos textos.

### 1. Preguntas de una clienta (2 min)

| Clienta escribe | Qué mostrarle |
|---|---|
| `Hola, buenas tardes` | Saluda y ofrece ayuda |
| `¿Cuánto cuesta el baño completo para un perro grande?` | Responde con **sus** precios del tarifario, no inventa |
| `¿aceptan tarjeta?` | **No lo sabe y no inventa:** le llega a ella (derecha) "❓ Pregunta sin respuesta…" |

**Propietaria** (derecha): `sí, también aceptamos tarjeta` → la respuesta le llega a la clienta.

> **Para decirle:** "Cuando no sabe algo, te pregunta a ti y le pasa tu respuesta al cliente. No se inventa nada."

### 2. Agendar una cita completa (4 min)

Primero los datos del perro, después la foto y al final el horario. A la clienta el bot le habla en
nombre del salón ("le confirmamos"); solo el saludo inicial dice que es un asistente virtual.

| Clienta escribe | Qué mostrarle |
|---|---|
| `Quiero agendar un baño completo para mi perrita Luna, es mestiza` | Pregunta por nudos y comportamiento (tranquilo, nervioso o agresivo) |
| `¿qué días tienen disponibles?` | "Con gusto le reviso la disponibilidad. **Primero necesito hacerle unas preguntas**" y repite la pregunta |
| `Tiene algunos nudos pero es tranquila` | Pregunta cómo es su pelo |
| `Su pelo le crece y hay que cortárselo` | Pregunta por vacunas y desparasitación |
| `Sí, tiene sus vacunas y está desparasitada` | **Pide una foto actual** de cuerpo entero |
| 📷 enviar la foto del perro | "¡Gracias por la foto!" y muestra **todos** los turnos libres de los próximos días |
| `¿tienen el jueves a las 10?` | Responde si está libre y pregunta **"¿Se lo reservo?"** (no lo da por confirmado) |
| `sí` | Le dice que se lo confirman en un momento |

A la derecha le llega **la foto y el resumen de la cita**: mascota, servicio, horario, precio propuesto, vacunas y
**lo que el sistema vio en la foto** (tamaño, pelo y nudos, con su porcentaje de confianza).

> **Para decirle:** "Tú ves la foto y el precio que propone el sistema, y apruebas o corriges. Si el perro es más
> grande, escribe `es grande` y el precio se recalcula."

El puerta a puerta no se ofrece: solo si la clienta lo pide (`que la recojan en mi casa, vivo en el Condado`), y
entonces suma el traslado. Si pide un **Premium sin el baño medicado**, el bot le recomienda el Baño Completo.

### 3. Ella decide (2 min)

**Propietaria:** `listo` → la clienta recibe la **confirmación** con fecha, servicio y total.

> **Para decirle:** "Ninguna cita se confirma sin ti. Puedes decir 'listo', 'no' o cambiar algo: 'es grande', 'cóbrale 20', 'a las 12 está bien'. Si cambias algo, se lo propone a la clienta antes de confirmar."

Si hay tiempo, mostrar el cambio: otra clienta pide cita, y la propietaria responde `a las 12 estaría mejor` → la clienta recibe la propuesta y responde `sí, perfecto`.
O si ese día no puede: `el lunes no puedo, el total sería 22` → a la clienta le ofrece turnos de otros días con el precio nuevo.

### 4. Después del servicio y contingencia (1 min)

| Propietaria escribe | Para qué |
|---|---|
| `cobré 25 a la cita #1` | Registra lo que cobró, para medir si las cotizaciones mejoran |
| `pausar bot` | Si algo falla o quiere atender ella: cada mensaje le llega directo |
| `activar bot` | El asistente vuelve a atender |

### 5. El panel (1 min)

1. Botón **Cargar datos de ejemplo** (barra superior): crea citas simuladas para que se vea lleno.
2. Pestaña **Panel de la dueña:** citas, ingresos, tiempo hasta confirmar, decisiones de la propietaria y la diferencia entre lo cotizado y lo cobrado.
3. Pestaña **Agenda:** la semana con las citas. Con Google Calendar, además aparecerán en el Calendario de su iPhone.

> **Aclararle:** los datos de ejemplo son simulados.

## Si algo falla durante la demo

| Problema | Qué hacer |
|---|---|
| Tarda más de 15 s en responder | Esperar: Gemini a veces tarda. Comentar que en WhatsApp es igual de rápido |
| Responde distinto de lo esperado | Seguir con naturalidad: "es un prototipo; por eso lo validamos contigo" |
| Error técnico o el panel no carga | Recargar la página. Si persiste, mostrar el escenario grabado: `python -m scripts.escenarios mestiza_puerta_a_puerta --solo-lectura` (no gasta créditos) |
| Se mezclan los mensajes de dos conversaciones | **Reiniciar demo** y empezar ese bloque de nuevo |

## Al terminar

- Compartirle la [guía de una página](guia_propietaria.md).
- Seguir con la [hoja de la reunión](reunion_propietaria.md): Meta, número, calendario, precios, siglas, chats, fotos y consentimiento.
