# Esquema de contenido de la base vectorial (SCRUM-99)

Qué se indexa en la base vectorial del agente RAG, de dónde sale cada dato,
cómo se redacta y qué falta validar con la propietaria. Alimenta SCRUM-66
(contenido) y SCRUM-67 (indexación). Versión 1.0 · 11-oct-2026.

## 1. Categorías de contenido

| Categoría | Qué cubre | Dónde vive | Cómo se genera |
|---|---|---|---|
| `negocio` | Quiénes somos, canal de atención, otros servicios, privacidad | `conocimiento/01_negocio.md` | Redactado |
| `servicios` | Qué incluye cada servicio, deslanado, desenredo | `conocimiento/02_servicios.md` | Redactado (inclusiones del catálogo) |
| `tarifario` | Precios por servicio y tamaño, tipos de pelo, recargos, descuento por varias mascotas | `app/cotizacion/tarifario_v2.json` | **Generado** al indexar |
| `cotizacion` | Cómo se calcula el precio, foto, mestizos, ajustes, pedidos especiales | `conocimiento/03_cotizacion.md` | Redactado |
| `agenda` | Cómo agendar, aprobación de la propietaria, cambios y cancelación, datos de mascota nueva | `conocimiento/04_agenda.md` | Redactado |
| `horarios` | Horario de atención | `app/agenda/config_agenda.json` | **Generado** al indexar (el mismo horario con el que se agenda) |
| `puerta_a_puerta` | Funcionamiento, costos por sector, restricción vehicular | `conocimiento/05_puerta_a_puerta.md` + tarifario | Redactado + **generado** |
| `politicas` | Perros que no se atienden, comportamiento, pago, factura | `conocimiento/06_politicas.md` + tarifario | Redactado + **generado** |
| `faq` | Preguntas frecuentes en formato pregunta → respuesta | `conocimiento/07_preguntas_frecuentes.md` | Redactado |

**Una sola fuente de verdad:** los precios y el horario nunca se escriben en los
`.md`. Se generan desde el tarifario y desde la configuración de la agenda, así
el asistente no puede contestar un precio o un horario distinto del que usa para
cotizar y agendar.

## 2. Metadatos de cada fragmento

Cada documento empieza con un encabezado:

```
---
categoria: servicios
fuente: catálogo publicado por el negocio y audios de la propietaria (tarifario v2)
vigente_desde: 2026-10-04
validado_por_propietaria: parcial      # no | parcial | si
---
```

Cada sección `## ` del documento es un fragmento, y hereda esos metadatos. Se
guardan en el índice (`indice_local.json`, o la columna `metadatos` en Supabase)
para trazabilidad y para filtrar por categoría si hiciera falta. Los fragmentos
generados llevan su propia fuente (versión del tarifario, archivo de agenda).

**Regla de oro:** todo lo que depende de un dato que cambia (precio, horario,
restricción vehicular) lleva `vigente_desde`. Si el dato cambia, se edita la
fuente y se re-indexa (`python -m app.rag.indexador`, ver `README.md`).

## 3. Cómo redactar

- **Una sección = una idea que se entiende sola.** El asistente recupera
  secciones sueltas: no escribir "como se dijo arriba".
- **Título = la pregunta o el tema tal como lo diría un cliente.** En las FAQ,
  el título es la pregunta (`## ¿Cómo se paga el servicio?`).
- **Tratar de "usted"**, en español de Ecuador, frases cortas.
- **Solo hechos con respaldo** (propietaria, catálogo, historial de WhatsApp).
  Si un dato no está confirmado, no se escribe: es preferible que el asistente
  diga "no tengo esa información" y le pase la pregunta a la propietaria.
- **Nunca datos de clientes** (nombres, teléfonos, direcciones, nombres de
  mascotas reales) — RNF-03, LOPDP.
- **No escribir promociones puntuales como política** (p. ej. un regalo que se
  hizo una vez a un cliente nuevo) ni el descuento por fidelidad, que según la
  propietaria no se ofrece: solo se aplica si el cliente lo pide.

## 4. Información pendiente (fuera de la base a propósito)

El asistente responde "no tengo esa información" y releva la pregunta a la
propietaria para estos temas, hasta que ella los confirme:

| Tema | Por qué falta |
|---|---|
| Dirección exacta del salón y sectores "aledaños" del traslado | Dato no entregado; afecta el costo del traslado más barato |
| Otros medios de pago (tarjeta, efectivo) | Solo consta la transferencia bancaria |
| Duración de cada servicio | En el tarifario v2 casi todas las duraciones son supuestos del equipo |
| Si el cliente puede quedarse durante el servicio o debe dejar a la mascota | Sin dato |
| Si se atienden gatos | El álbum de Facebook tiene fotos de gatos, pero el negocio se describe como grooming canino |
| Equivalencia con los códigos internos del Excel (SC, SB, SP, BA, BM, BB, SBas) | Pendiente H2 de SCRUM-74 |

## 5. Lista para validar con la propietaria (criterio de aceptación de SCRUM-66)

Marcar cada punto como correcto o corregirlo. Al terminar, cambiar
`validado_por_propietaria` a `si` en cada documento y re-indexar.

- [ ] Horario: lunes, miércoles y viernes de 11:00 a 18:00; martes, jueves,
      sábado y domingo de 08:00 a 18:00 (`config_agenda.json`).
- [ ] Más de 4 años de experiencia; atención solo por WhatsApp.
- [ ] Hospedaje y snacks: los atiende ella directamente.
- [ ] Lo que incluye cada uno de los cuatro baños (catálogo).
- [ ] Deslanado solo para perros de doble capa y cobrado aparte.
- [ ] Desenredo si el pelo es recuperable; si no, se rapa.
- [ ] El precio puede ajustarse el día del servicio por nudos o comportamiento.
- [ ] Pedidos especiales: ella define el precio.
- [ ] Datos que se piden de una mascota nueva: edad, vacunas, desparasitación,
      enfermedades y temperamento.
- [ ] Varias mascotas: descuento por mascota y traslado cobrado una vez por visita.
- [ ] No se atienden perros agresivos ni de más de 45 kg.
- [ ] Perros nerviosos: pequeño recargo.
- [ ] Pago por transferencia al finalizar; se emite factura.
- [ ] Los temas de la sección 4.

## 6. Relación con el código

- `app/rag/fragmentador.py`: lee los documentos y su encabezado, y genera los
  fragmentos del tarifario y del horario.
- `app/rag/indexador.py`: re-indexado incremental (solo lo que cambió, incluidos
  los metadatos).
- `app/rag/esquema_pgvector.sql`: tabla para Supabase con columna `metadatos`.
