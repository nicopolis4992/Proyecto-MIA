# NLU con mensajes reales (n = 283)

| Modelo | Exactitud (IC 95 %) | F1 macro (IC 95 %) | F1 agendar / consultar / general |
|---|---|---|---|
| gemini-3.5-flash-lite (prompt v2) | 0.894 [0.859, 0.926] | 0.814 [0.735, 0.878] | 0.842 / 0.667 / 0.932 |
| TF-IDF + RL | 0.792 [0.742, 0.837] | 0.63 [0.545, 0.707] | 0.676 / 0.343 / 0.871 |

McNemar exacta: el modelo de lenguaje acierta y la línea base falla en 38 mensajes; al revés en 9 (p = 2.5e-05).

| Cliente | n | Exactitud LLM | F1 LLM | Exactitud base | F1 base |
|---|---|---|---|---|---|
| cliente_1 | 148 | 0.872 | 0.792 | 0.743 | 0.601 |
| cliente_2 | 44 | 0.955 | 0.85 | 0.818 | 0.491 |
| cliente_3 | 44 | 0.909 | 0.926 | 0.886 | 0.795 |
| cliente_4 | 47 | 0.894 | 0.745 | 0.83 | 0.577 |

Cuatro clientes, un solo etiquetado sin segundo anotador: la mayoría de los mensajes son de cortesía y logística (consulta general) y la clase consultar tiene pocos casos.
