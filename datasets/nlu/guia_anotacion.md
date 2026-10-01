# Guía de anotación — Agente NLU

**Proyecto MIA — Lina's Pet Salón** · Historia SCRUM-63 · Épica SCRUM-53
Versión 1.0 · Septiembre 2026

---

## 1. Para qué sirve este documento

Dos personas que etiquetan el mismo mensaje deben llegar a la misma intención. Sin
una regla escrita eso no ocurre: cada anotador resuelve los casos ambiguos con su
propio criterio y el clasificador termina aprendiendo el desacuerdo en lugar de la
tarea. Esta guía fija esas reglas antes de que empiece la anotación, y define cómo
se mide si funcionaron.

Aplica tanto al corpus semilla como al corpus real que se obtenga del export de
WhatsApp Business.

---

## 2. Qué se anota

Solo los mensajes **enviados por el cliente**. Los mensajes de la propietaria no se
etiquetan con intención: alimentan la base de conocimiento del agente RAG
(SCRUM-99), que es otra historia.

La unidad de anotación es el **mensaje individual**, no el turno ni la conversación.
Un cliente que envía tres mensajes seguidos genera tres registros.

---

## 3. Las tres intenciones

### `agendar_cita`

El cliente quiere **mover el estado de una cita**: crearla, consultar si hay cupo
para crearla, reprogramarla, cancelarla o confirmarla.

Incluye:

- Solicitud explícita ("quiero agendar", "me da un turno")
- Consulta de disponibilidad ("hay campo el sábado?", "tiene espacio?")
- Reprogramación y cancelación
- Confirmación de una propuesta de horario ("dale, resérveme esa hora")
- Consulta sobre una cita ya existente ("a qué hora era mi turno?")

### `consultar_servicio_producto`

El cliente pregunta por **qué se ofrece, cuánto cuesta o qué incluye**, sin pedir
todavía un espacio en la agenda.

Incluye:

- Precio de cualquier servicio, recargo o producto
- Alcance del servicio ("qué incluye el baño?", "cortan uñas?")
- Duración del servicio
- Snacks, shampoos y productos
- Envío de foto de la mascota con propósito de cotización

### `consulta_general`

Todo lo demás que sí es una interacción legítima con el negocio: logística,
cortesía y postventa.

Incluye:

- Ubicación, horarios, formas de pago, facturación
- Saludos, agradecimientos, despedidas
- Seguimiento durante el servicio ("ya está listo?", "ya llegué")
- Comentarios y reclamos posteriores al servicio
- Requisitos previos (vacunas, correa, desparasitación)
- Redes sociales y fotos del trabajo

---

## 4. Reglas de desambiguación

Se aplican **en orden**. La primera que resuelva el caso decide.

**R1 — Prioridad por acción.** Si un mensaje contiene más de una intención, gana la
que exige una acción operativa de la propietaria, según esta jerarquía:

```
agendar_cita  >  consultar_servicio_producto  >  consulta_general
```

> *"¿Cuánto cuesta el baño y tiene espacio mañana?"* → `agendar_cita`
> Razón: la disponibilidad bloquea la agenda; el precio no.

**R2 — La foto sola no agenda.** Enviar la fotografía de la mascota es, por sí
misma, `consultar_servicio_producto`: en el proceso actual la foto es el insumo de
la cotización. Solo pasa a `agendar_cita` si el mensaje además pide un horario.

**R3 — El precio del domicilio es servicio, no logística.** Preguntar cuánto cuesta
el traslado puerta a puerta es `consultar_servicio_producto`. Preguntar **hasta
dónde** llega el servicio o **por qué sector** queda el local es `consulta_general`.

> Esta frontera es la que más errores produjo en la línea base. Al anotar, la
> pregunta de control es: *¿la respuesta correcta es un monto en dólares?* Si sí,
> es `consultar_servicio_producto`.

**R4 — La confirmación hereda el hilo.** Respuestas cortas como "ok", "dale",
"perfecto" se etiquetan según lo que confirman. Si confirman un horario propuesto,
son `agendar_cita`. Si solo cierran una conversación, son `consulta_general`. Si el
anotador no puede reconstruir el hilo, el mensaje se marca `DESCARTAR`.

**R5 — Facturación es general.** Pedir factura, preguntar por medios de pago o
enviar el comprobante es `consulta_general`, aunque mencione montos: no se está
consultando una tarifa, se está ejecutando un pago.

**R6 — Servicios fuera de alcance igual se etiquetan.** Hospedaje y snacks están
fuera del alcance funcional del sistema, pero las preguntas por su precio siguen
siendo `consultar_servicio_producto`. El NLU debe reconocerlas para poder derivarlas
a la propietaria en lugar de fallar.

**R7 — Marcar `DESCARTAR`, no adivinar.** Se descarta el mensaje cuando es ruido de
sistema ("<Multimedia omitido>"), cuando el texto por sí solo no permite decidir, o
cuando es un mensaje equivocado ajeno al negocio. Un descarte honesto vale más que
una etiqueta inventada.

---

## 5. Entidades

Se anotan a nivel de mensaje, solo si el cliente las declara de forma explícita. No
se infieren.

| Entidad | Valores | Nota |
|---|---|---|
| `tamano` | `pequeno`, `mediano`, `grande` | Solo si el cliente lo dice. La raza **no** se traduce a tamaño en esta etapa. |
| `pelaje` | `corto`, `largo`, `rizado`, `doble_capa` | Igual criterio. |
| `modalidad` | `salon`, `puerta_a_puerta` | |
| `num_mascotas` | entero ≥ 1 | Solo si se menciona más de una o se dice explícitamente. |
| `raza` | texto libre | Tal como lo escribe el cliente, sin normalizar ni corregir. |
| `temporalidad` | texto libre | Expresión cruda ("el sábado", "mañana a las 3"). La normalización a fecha es responsabilidad del agente de agenda. |

**La ausencia de una entidad es información.** Si el cliente no declaró el tamaño,
el campo no se inventa: el agente deberá preguntarlo. Rellenar huecos por inferencia
del anotador es el error más costoso de esta etapa, porque enseña al sistema a
suponer justo lo que el proyecto busca dejar de suponer.

---

## 6. Control de calidad: acuerdo inter-anotador

1. **Doble anotación ciega.** Dos integrantes del equipo etiquetan de forma
   independiente el mismo subconjunto: el **20% del corpus**, seleccionado al azar
   con semilla fija.
2. **Cálculo del coeficiente κ de Cohen** sobre ese subconjunto.
3. **Umbral de aceptación: κ ≥ 0.80.** En la escala de Landis y Koch (1977) ese
   valor corresponde a acuerdo *casi perfecto*. Por debajo de 0.80 **no se continúa
   anotando**: se revisan los desacuerdos, se corrige esta guía y se vuelve a medir.
4. **Registro obligatorio.** Cada iteración deja constancia de la fecha, el valor de
   κ y qué regla se modificó. Ese registro es el que sustenta la validez del dataset
   en el informe de titulación; sin él, la calidad del etiquetado es una afirmación
   sin respaldo.
5. **Resolución de desacuerdos.** Los casos discrepantes los resuelve el tercer
   integrante, que no participó en la doble anotación.

```python
from sklearn.metrics import cohen_kappa_score
kappa = cohen_kappa_score(anotador_a, anotador_b)
```

---

## 7. Volumen mínimo por intención

La referencia es CLINC150 (Larson et al., 2019), que trabaja con 150 ejemplos por
intención, y la evidencia de detección de intención con pocos ejemplos de Casanueva
et al. (2020), que reporta desempeño utilizable a partir de 10–30 ejemplos por clase
cuando se usan codificadores preentrenados.

Para este proyecto se fija:

| Umbral | Ejemplos por intención | Uso |
|---|---|---|
| Mínimo operativo | 30 | Permite arrancar el desarrollo del agente |
| **Meta del corpus real** | **80** | Valor comprometido para la evaluación de SCRUM-90 |
| Deseable | 150 | Alinea con el estándar de CLINC150 |

El corpus semilla ya supera el mínimo operativo en las tres clases. La meta de 80 se
mide **solo sobre enunciados reales**, no sobre los sintéticos.

---

## 8. Registro de versiones

| Versión | Fecha | Cambio |
|---|---|---|
| 1.0 | 2026-09-13 | Versión inicial. Reglas R1–R7 y esquema de entidades. |
