# Línea base: revisión manual (26-oct-2026)

Cuatro chats reales de WhatsApp Business (clientes distintos, 2024–2026, 2 467 mensajes),
procesados con `linea_base_whatsapp.py`. Los textos no salen de `datos_crudos/` (LOPDP).

| Indicador | Resultado | Revisión manual | Uso en el informe |
|---|---|---|---|
| Primera respuesta de la propietaria | Mediana 1,5 min (n = 702; mismo día: 1,1 min, n = 642) | Sin observaciones | Complementario |
| Tiempo hasta confirmar una cita | Mediana 21,1 min (n = 47); p75 133 min; p90 27 h | Muestra de 12: los 12 son un pedido de turno seguido de "le agendo" o equivalente | **Línea base del tiempo** |
| Variación de precio (detección automática) | Mediana 10 USD (n = 21) | La mayoría son falsos positivos: total y precio por mascota en el mismo mensaje, costo del traslado, costo de una veterinaria | **No se usa** |

La variabilidad entre lo cotizado y lo cobrado no se puede medir con los chats: el cobro final
de la misma mascota casi nunca aparece junto a la cotización. La línea base de la variabilidad
es la declarada por la propietaria (5 a 10 USD, entrevista del 2-ago), respaldada por los chats:
cotiza en rangos ("entre 12 a 15 $", "15 $ y si está muy motoso 18 $") y advierte que "los valores
que se brindan por WhatsApp son estimados, la valoración real se da el día de su cita".
