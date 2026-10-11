# Evaluación NLU — prompt v2 (gemini-3.5-flash-lite)

Conjunto: **entrenamiento** (222 mensajes). Corpus mayoritariamente sintético (SCRUM-63): mide acuerdo con la guía de anotación, no desempeño en producción. Recalcular con el corpus real anotado.

| Métrica | Gemini (bot) |
|---|---|
| Exactitud | 0.960 |
| F1 macro | 0.958 |
| F1 ponderado | 0.960 |

**Por clase**

| Intención | Precisión | Recall | F1 | n |
|---|---|---|---|---|
| agendar | 0.988 | 0.976 | 0.982 | 85 |
| consultar | 0.984 | 0.926 | 0.955 | 68 |
| general | 0.905 | 0.971 | 0.937 | 69 |

**Matriz de confusión** (filas = real, columnas = predicho)

| | agendar | consultar | general |
|---|---|---|---|
| **agendar** | 83 | 0 | 2 |
| **consultar** | 0 | 63 | 5 |
| **general** | 1 | 1 | 67 |

**Confianza media:** aciertos 0.962 · errores 0.944
**Entidades:** recall fecha/hora 0.978 (n=45) · falsas fechas 0.045 · recall tipo de mascota 1.0 (n=27)
**Latencia mediana:** 752 ms (0 si vino de la grabación)

**Errores (9)**

| id | Mensaje | Real | Predicho | Conf. |
|---|---|---|---|---|
| MIA-0032 | me recuerda a que hora tengo el turno porfa | agendar | general | 0.95 |
| MIA-0102 | buenas, voy a llegar 15 min tarde a mi cita, no hay problema? | agendar | general | 0.95 |
| MIA-0140 | cuanto se demora el servicio? | consultar | general | 0.90 |
| MIA-0142 | es rapido? tengo que esperar o le dejo? | consultar | general | 0.95 |
| MIA-0143 | me puedo quedar mientras le atiende? | consultar | general | 0.95 |
| MIA-0152 | hacen envio de los snacks? | consultar | general | 0.95 |
| MIA-0190 | el precio que me dio es el final o puede cambiar? | consultar | general | 0.95 |
| MIA-0213 | manana atienden normal? | general | agendar | 0.95 |
| MIA-0244 | tiene fotos de cortes para escoger? | general | consultar | 0.95 |
