# SCRUM-64 — Evaluación del agente NLU

Clasificación de intención (agendar / consultar / general) y extracción de
entidades del NLU del bot (`app/agents/nlu_extractor.py`, Gemini 3.5 Flash-Lite,
sin entrenamiento: instrucciones + salida estructurada), contra el conjunto de
prueba de SCRUM-63 (`datasets/nlu/dataset_nlu_test.csv`, 56 mensajes) y la línea
base TF-IDF + regresión logística de la misma entrega.

```bash
python -m evaluacion.nlu.evaluar_nlu                      # set de prueba
python -m evaluacion.nlu.evaluar_nlu --conjunto entrenamiento  # 222, ciego para el prompt
python -m evaluacion.nlu.evaluar_nlu --conjunto completo  # los 278
python -m evaluacion.nlu.evaluar_nlu --solo-lectura       # sin llamar a Gemini
```

## Resultados (set de prueba, 56 mensajes)

| | F1 macro | Exactitud | Errores | Confianza media (aciertos / errores) |
|---|---|---|---|---|
| Línea base TF-IDF (SCRUM-63) | 0.963 | — | 2 | — |
| NLU prompt **v1** | 0.925 | 0.929 | 4 | 0.95 / 0.94 |
| NLU prompt **v2** | **1.000** | **1.000** | 0 | 0.97 / — |

Detalle: `resultados/nlu_v1_prueba.md` y `resultados/nlu_v2_prueba.md`.

## Estimación limpia: v2 sobre el conjunto de entrenamiento (222, ciego)

El NLU no se entrena, así que los 222 mensajes de entrenamiento de SCRUM-63 —que
no se inspeccionaron al escribir los prompts— funcionan como conjunto ciego.
**Esta es la cifra a reportar.** (No se compara con la línea base TF-IDF, que se
entrenó con esos mismos mensajes.)

| | F1 macro | Exactitud | Errores | Confianza media (aciertos / errores) |
|---|---|---|---|---|
| NLU prompt **v2**, 222 mensajes ciegos | **0.958** | 0.960 | 9 | 0.96 / 0.94 |

| Intención | Precisión | Recall | F1 | n |
|---|---|---|---|---|
| agendar | 0.988 | 0.976 | 0.982 | 85 |
| consultar | 0.984 | 0.926 | 0.955 | 68 |
| general | 0.905 | 0.971 | 0.937 | 69 |

Los 9 errores (`resultados/nlu_v2_entrenamiento.md`) se concentran en dos
fronteras de la guía que el prompt v2 no cubre de forma explícita:

- **Atributos del servicio que parecen logística** (5 de 9): "¿cuánto se demora el
  servicio?", "¿tengo que esperar o le dejo?", "¿me puedo quedar mientras le
  atiende?", "¿el precio que me dio es el final?", "¿hacen envío de los snacks?".
  La guía los anota `consultar` (preguntan por el servicio); v2 los toma como
  logística → `general`.
- **Gestión de una cita existente** (2): "¿a qué hora tengo el turno?", "voy a
  llegar 15 min tarde a mi cita" → la guía dice `agendar`; v2 dice `general`.
- Otros 2 casos aislados ("mañana atienden normal?", "¿tiene fotos de cortes?").

No se ajustó el prompt con estos errores, para no contaminar el único conjunto
ciego disponible. Un v3 que precise esas dos fronteras debe evaluarse sobre el
corpus real anotado. Impacto en el bot: los 7 casos principales terminan en el
agente general, que no inventa y releva la pregunta a la propietaria; el costo es
una consulta más para ella, no una respuesta incorrecta.

## Qué cambió de v1 a v2

Los 4 errores de v1 no eran fallas del modelo sino **diferencias de definición**
entre el prompt y la guía de anotación (`datasets/nlu/guia_anotacion.md`):

| Mensaje | Guía | v1 |
|---|---|---|
| "quisiera saber qué días tiene libres esta semana" | agendar (R1: la disponibilidad ocupa la agenda) | consultar |
| "¿puedo pagar con tarjeta?" | general (R5: pagos y facturación) | consultar |
| "¿a qué hora le puedo ir a recoger?" | general (logística) | consultar |
| "¿llevo su toalla o ustedes ponen?" | general (logística) | consultar |

v2 reescribe las definiciones de las tres intenciones con las reglas R1–R6 de la
guía. Efecto en el bot: las preguntas de disponibilidad van a la agenda (que
responde con horarios reales) y las de pagos o logística al agente general, que
**no las inventa**: las releva a la propietaria (`CONSULTAR_PROPIETARIA`).

## Limitaciones (para el informe)

1. **El 100 % de v2 en el set de prueba es optimista** (la estimación limpia es
   0.958, ver arriba). v2 se escribió después de ver los errores de
   v1 sobre este mismo conjunto. Las reglas vienen de la guía, no de los
   mensajes, pero el conjunto ya no es "ciego". Una estimación limpia requiere un
   conjunto no inspeccionado: el de entrenamiento (222 mensajes, nunca revisados
   para este fin) o, mejor, el corpus real anotado.
2. **Corpus sintético** (advertencia de SCRUM-63): mide acuerdo con la guía, no
   desempeño en producción.
3. **La confianza autodeclarada del LLM no discrimina** (0.95 en aciertos vs.
   0.94 en errores en v1). No sirve como umbral para pedir aclaración (SCRUM-62):
   hace falta otra señal (p. ej. desacuerdo entre dos clasificadores o reglas).
4. La línea base TF-IDF se entrenó con mensajes del mismo generador sintético que
   el conjunto de prueba, lo que la favorece; el NLU del bot no vio ningún ejemplo.

## Entidades

Set de prueba, ambos prompts: recall de fecha/hora 1.0 (n=14), recall de tipo de
mascota 1.0 (n=7); fechas inventadas en mensajes sin temporalidad: 4.8 % (v1) →
2.4 % (v2). Conjunto ciego (v2): recall de fecha/hora 0.978 (n=45), tipo de mascota
1.0 (n=27), fechas inventadas 4.5 %.
