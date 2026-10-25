# Evaluación del RAG (SCRUM-71)

59 preguntas: 40 que la base sabe, 19 que debe declinar.

| Métrica | Valor |
|---|---|
| Recuperación: categoría correcta en 1.er lugar | 95.0 % |
| Recuperación: categoría correcta entre los 4 primeros | 100.0 % |
| Exactitud de las respuestas | 82.5 % |
| "No sé" correcto | 100.0 % |
| Alucinación (respondió cuando debía declinar) | 0.0 % |

## Umbral de similitud

| | Umbral | Responde lo que sabe | Declina lo que no sabe | Exactitud balanceada |
|---|---|---|---|---|
| Actual | 0.66 | 100.0 % | 52.6 % | 76.3 % |
| Propuesto | 0.7 | 90.0 % | 94.7 % | 92.3 % |

## Casos a revisar

| Pregunta | Esperado | Problema |
|---|---|---|
| q trae el baño completo? | servicios|tarifario | recuperó ['cotizacion', 'tarifario'] (esperado servicios|tarifario) |
| el premium q tiene de diferente al completo | servicios|tarifario|faq | recuperó ['cotizacion', 'faq'] (esperado servicios|tarifario|faq) |
| mi perrita tiene el pelo todo enredado con motas la pueden atender? | servicios|tarifario | no respondió |
| xq me cobrarian mas el dia del baño | cotizacion|faq|tarifario|servicios | faltan: enredado |
| mi schnauzer cuenta como pequeño o mediano? | cotizacion|tarifario | no respondió |
| mi perro es bravo lo reciben? | politicas|tarifario | no respondió |
| cuanto cobran x ir a ver al perro en el condado | puerta_a_puerta | no respondió |
| q es lina's pet salon? q hacen | negocio | no respondió |
| cuantos años de experiencia tiene la peluquera | negocio | no respondió |

Umbral propuesto con el mismo conjunto evaluado: confirmarlo con preguntas nuevas antes de fijarlo.
