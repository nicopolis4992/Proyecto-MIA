# Tarifario v2.3.0 frente a lo cobrado (Excel de la propietaria)

Registros con monto: 708. Excluidos: bano_especial 7, con_extras 39, raza_no_reconocida 9, sin_codigo 311, sin_raza 33.

| Grupo | n | Dentro del rango | Dif. media (USD) | Dif. mediana | Error abs. medio |
|---|---|---|---|---|---|
| En el salón | 255 | 78.4 % | -12.16 | -16.0 | 12.85 |
| En el salón, raza que fija tamaño y pelo | 79 | 58.2 % | -1.92 | 0.0 | 4.11 |
| Servicio: completo | 227 | 79.7 % | -12.59 | -16.0 | 13.22 |
| Servicio: express | 28 | 67.9 % | -8.72 | -11.0 | 9.83 |
| Año 2024 | 27 | 85.2 % | -11.67 | -16.0 | 12.93 |
| Año 2025 | 175 | 74.9 % | -11.99 | -16.0 | 12.71 |
| Año 2026 | 53 | 86.8 % | -12.97 | -16.0 | 13.27 |
| Con puerta a puerta (monto con traslado) | 54 | 90.7 % | -7.55 | -11.0 | 9.81 |

## Baño Completo por raza (en el salón, 3 o más servicios)

| Raza | n | Cobrado (mediana) | Cobrado (mín–máx) | Motor sin nudos | Rango del motor | Dentro |
|---|---|---|---|---|---|---|
| shih tzu | 26 | 14 | 6–15 | 12 | 12–16 | 76.9 % |
| pequines | 12 | 12 | 10–20 | 12 | 12–16 | 50.0 % |
| castellano | 8 | 14 | 12–20 | 16 | 16–20 | 50.0 % |
| yorkie | 7 | 15 | 6.3–15 | 15 | 15–20 | 57.1 % |
| pastor ingles | 5 | 25 | 12–45 | 45 | 45–70 | 20.0 % |
| golden | 5 | 25 | 25–25 | 25 | 25–39 | 100.0 % |

dentro_del_rango: lo cobrado cae en el rango que el bot daria sabiendo raza y servicio (sin saber nudos). cobrado_menos_motor_sin_nudos > 0: ella cobra mas que el precio sin nudos del motor (puede ser por nudos, que el Excel no registra).
