# Evaluación NLU — prompt v2 (gemini-3.5-flash-lite)

Conjunto: **prueba** (56 mensajes). Corpus mayoritariamente sintético (SCRUM-63): mide acuerdo con la guía de anotación, no desempeño en producción. Recalcular con el corpus real anotado.

| Métrica | Gemini (bot) | Línea base TF-IDF |
|---|---|---|
| Exactitud | 1.000 | — |
| F1 macro | 1.000 | 0.963 |
| F1 ponderado | 1.000 | 0.964 |

**Por clase**

| Intención | Precisión | Recall | F1 | n |
|---|---|---|---|---|
| agendar | 1.000 | 1.000 | 1.000 | 22 |
| consultar | 1.000 | 1.000 | 1.000 | 17 |
| general | 1.000 | 1.000 | 1.000 | 17 |

**Matriz de confusión** (filas = real, columnas = predicho)

| | agendar | consultar | general |
|---|---|---|---|
| **agendar** | 22 | 0 | 0 |
| **consultar** | 0 | 17 | 0 |
| **general** | 0 | 0 | 17 |

**Confianza media:** aciertos 0.968 · errores None
**Entidades:** recall fecha/hora 1.0 (n=14) · falsas fechas 0.024 · recall tipo de mascota 1.0 (n=7)
**Latencia mediana:** 775 ms (0 si vino de la grabación)

**Errores (0)**

| id | Mensaje | Real | Predicho | Conf. |
|---|---|---|---|---|
