# SCRUM-64 — Evaluación del agente NLU

Clasificación de intención (agendar / consultar / general) y extracción de
entidades del NLU del bot (`app/agents/nlu_extractor.py`, Gemini 3.5 Flash-Lite,
sin entrenamiento: instrucciones + salida estructurada), contra el conjunto de
prueba de SCRUM-63 (`datasets/nlu/dataset_nlu_test.csv`, 56 mensajes) y la línea
base TF-IDF + regresión logística de la misma entrega.

```bash
python -m evaluacion.nlu.evaluar_nlu                      # set de prueba
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

1. **El 100 % de v2 es optimista.** v2 se escribió después de ver los errores de
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

En ambos prompts: recall de fecha/hora 1.0 (n=14), recall de tipo de mascota 1.0
(n=7); fechas inventadas en mensajes sin temporalidad: 4.8 % (v1) → 2.4 % (v2).
