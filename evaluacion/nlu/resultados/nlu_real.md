# NLU con mensajes reales (n = 148)

| Modelo | Exactitud (IC 95 %) | F1 macro (IC 95 %) | F1 agendar / consultar / general |
|---|---|---|---|
| gemini-3.5-flash-lite (prompt v2) | 0.872 [0.811, 0.926] | 0.792 [0.683, 0.88] | 0.793 / 0.667 / 0.916 |
| TF-IDF + RL | 0.743 [0.669, 0.811] | 0.601 [0.488, 0.704] | 0.562 / 0.4 / 0.841 |

McNemar exacta: el modelo de lenguaje acierta y la línea base falla en 25 mensajes; al revés en 6 (p = 0.0009).

Una sola clienta: la muestra no representa la variedad de clientes; la mayoría de los mensajes son de cortesía y logística (consulta general).
