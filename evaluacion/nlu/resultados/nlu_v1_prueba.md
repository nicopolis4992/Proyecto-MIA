# Evaluación NLU — prompt v1 (gemini-3.5-flash-lite)

Conjunto: **prueba** (56 mensajes). Corpus mayoritariamente sintético (SCRUM-63): mide acuerdo con la guía de anotación, no desempeño en producción. Recalcular con el corpus real anotado.

| Métrica | Gemini (bot) | Línea base TF-IDF |
|---|---|---|
| Exactitud | 0.929 | — |
| F1 macro | 0.925 | 0.963 |
| F1 ponderado | 0.929 | 0.964 |

**Por clase**

| Intención | Precisión | Recall | F1 | n |
|---|---|---|---|---|
| agendar | 1.000 | 0.955 | 0.977 | 22 |
| consultar | 0.810 | 1.000 | 0.895 | 17 |
| general | 1.000 | 0.824 | 0.903 | 17 |

**Matriz de confusión** (filas = real, columnas = predicho)

| | agendar | consultar | general |
|---|---|---|---|
| **agendar** | 21 | 1 | 0 |
| **consultar** | 0 | 17 | 0 |
| **general** | 0 | 3 | 14 |

**Confianza media:** aciertos 0.95 · errores 0.938
**Entidades:** recall fecha/hora 1.0 (n=14) · falsas fechas 0.048 · recall tipo de mascota 1.0 (n=7)
**Latencia mediana:** 1 ms (0 si vino de la grabación)

**Errores (4)**

| id | Mensaje | Real | Predicho | Conf. |
|---|---|---|---|---|
| MIA-0098 | buenas, quisiera saber que dias tiene libres esta semana | agendar | consultar | 0.95 |
| MIA-0215 | puedo pagar con tarjeta? | general | consultar | 0.95 |
| MIA-0227 | a que hora le puedo ir a recoger? | general | consultar | 0.90 |
| MIA-0254 | llevo su toalla o ustedes ponen? | general | consultar | 0.95 |
