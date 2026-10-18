# Tarifario v2.1.0 frente a lo cobrado (Excel de la propietaria)

Registros con monto: 708. Excluidos: bano_especial 7, con_extras 39, raza_no_reconocida 19, sin_codigo 311, sin_raza 33.

| Grupo | n | Dentro del rango | Dif. media (USD) | Dif. mediana | Error abs. medio |
|---|---|---|---|---|---|
| En el salón | 247 | 68.4 % | -9.27 | -11.75 | 9.68 |
| En el salón, raza que fija tamaño y pelo | 71 | 45.1 % | -3.6 | -1.0 | 4.29 |
| Servicio: completo | 219 | 69.9 % | -9.83 | -12.5 | 10.02 |
| Servicio: express | 28 | 57.1 % | -4.91 | -5.25 | 7.0 |
| Año 2024 | 26 | 73.1 % | -8.93 | -12.12 | 9.49 |
| Año 2025 | 168 | 64.3 % | -9.47 | -11.75 | 9.92 |
| Año 2026 | 53 | 79.2 % | -8.81 | -11.5 | 9.0 |
| Con puerta a puerta (monto con traslado) | 52 | 90.4 % | -5.54 | -3.5 | 7.54 |

## Baño Completo por raza (en el salón, 3 o más servicios)

| Raza | n | Cobrado (mediana) | Cobrado (mín–máx) | Motor sin nudos | Rango del motor | Dentro |
|---|---|---|---|---|---|---|
| shih tzu | 26 | 14 | 6–15 | 15 | 15–20 | 46.2 % |
| pequines | 12 | 12 | 10–20 | 15 | 15–20 | 33.3 % |
| yorkie | 7 | 15 | 6.3–15 | 15 | 15–20 | 57.1 % |
| pastor ingles | 5 | 25 | 12–45 | 45 | 45–70 | 20.0 % |
| golden | 5 | 25 | 25–25 | 25 | 25–39 | 100.0 % |

dentro_del_rango: lo cobrado cae en el rango que el bot daria sabiendo raza y servicio (sin saber nudos). cobrado_menos_motor_sin_nudos > 0: ella cobra mas que el precio sin nudos del motor (puede ser por nudos, que el Excel no registra).
