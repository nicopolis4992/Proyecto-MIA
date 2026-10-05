# Tarifario v2 — Lina's Pet Salón (04/10/2026)

Contenido:

- `tarifario_v2.json`: todos los valores del negocio.
- `motor_cotizacion_v2.py`: motor sin precios en el código.
- `test_motor_v2.py`: 39 pruebas, todas en verde.

Ejecutar las pruebas: `python -m pytest -q`

## Qué cambió respecto a v1

| Tema | v1 (referencia) | v2 (datos de la propietaria) |
|---|---|---|
| Precios | Mercado de Quito | Catálogo: Express 7 · Básico 9 · Completo 12 · Premium 15 ("desde") |
| Pelaje | Factor por tipo (1,00–1,25) | Factor por **tamaño × grupo de manto** (máquina, deslanado, cepillado, corto), tomado de la raza |
| Motas | Atributo de la banda | Recargo porcentual por tamaño: moderado o severo |
| Adicionales | — | Deslanado como servicio aparte (pug 12; husky 25–35) |
| Exclusiones | > 45 kg | > 45 kg **y** perro declarado agresivo |
| Traslado | Monto fijo | Por zona: 0–3 / 5 / 10–15 |
| Varias mascotas | 10 % / 15 % desde 2 | USD 1–2 por mascota desde 4 |
| Banda | Puntos fijos por atributo, tope 25 % | **Enumeración de escenarios**: rango real [mín, máx] de los atributos no declarados |
| Umbral para comprometer el precio | USD 2,50 | USD 1,00 (decisión pendiente del equipo) |
| Duración | — | Rango en minutos por servicio y tamaño (casi todo SUPUESTO) |

## Validación contra la propietaria

Los 10 precios que dio en sus audios se reproducen exactamente, salvo uno:

| Caso | Propietaria | Motor |
|---|---|---|
| Shih tzu en buen estado | 15 | 15 |
| Shih tzu en mal estado | hasta 20 | 20 |
| Golden, peluquería completa | 25 | 25 |
| Pastor inglés, peluquería | 45 | 45 |
| Pastor inglés con nudos | hasta 70 | 70 |
| **Pastor inglés, solo baño** | **25** | **26,50** (único caso que no cuadra exacto) |
| Mestizo de rottweiler, baño medicado | 17 | 17 |
| Mestiza mediana | 18–22 | 18 sin motas · 22 con motas moderadas |
| Pug, deslanado | 12 | 12 |
| Husky, deslanado | 25–35 | 25–35 |

**Advertencia de circularidad:** los factores se calibraron con esos mismos casos, así que estas pruebas comprueban la implementación, no que el modelo generalice. La validación real es pedirle a la propietaria precios de casos nuevos (o tomarlos del Excel de cuentas) y compararlos con el motor.

## Trazabilidad

Cada valor del JSON lleva su `fuente`:

| Fuente | Significado | Celdas (aprox.) |
|---|---|---|
| CATALOGO / PROPIETARIA | Dato real | Pisos, 6 factores, recargos severos de pequeño y grande, traslado, descuentos, exclusiones |
| INTERPOLADO | Calculado de datos reales | 4 factores, 4 recargos, deslanado mediano, umbral |
| SUPUESTO | Provisional del equipo | 3 factores, grupos de razas no mencionadas, casi todas las duraciones, "traslado una vez por visita" |
| PENDIENTE | Sin dato | Recargo por comportamiento (0–20 % solo ensancha la banda), régimen de IVA |

## Para SCRUM-103 (Nico)

- **Entrada del motor por mascota:** `raza`, `tamano`, `grupo`, `estado`, `comportamiento`, `peso_kg`, `servicio`. Todos son opcionales salvo `servicio`.
- **Lo que debe aportar el clasificador de imagen:** `tamano`, `grupo` y `estado`.
- **La foto sola deja un rango muy amplio.** Con solo la foto y el servicio Completo, el rango es USD 12–84 y la pregunta de mayor impacto es el tamaño (USD 12). Lo que el clasificador logre fijar se nota directamente en ese rango.
- **Salida:** `rango`, `semiamplitud`, `comprometido`, `preguntas_sugeridas` (ordenadas por impacto en USD), `duracion_min` y `desglose`.
- **`Cotizacion.desde_motor()` de SCRUM-74** debe alinearse con esta salida.

## Cambios al integrar en el repo (Nico, 04/10/2026)

| Cambio | Motivo |
|---|---|
| Nombre real de la propietaria eliminado de `convencion_fuentes` | Anonimización acordada del proyecto |
| Rangos de peso 0–9 / 9,01–18 / 18,01–45 y comparación por límite superior | Un perro de 9,05 kg quedaba sin tamaño (rango USD 9–63) |
| Deslanado a un grupo que no lo admite → `no_aplica` + sugerencia de Completo | Antes cotizaba "deslanado de shih tzu" en USD 12 |
| `alias` por raza + coincidencia aproximada (`difflib`, umbral 0,8) | "shitsu", "golden retriever", "chiguagua" no se reconocían |
| Cruces ("schnauzer con poodle") = unión de ambas razas; "mestizo de X" = X con aviso | Mestizos y cruces son frecuentes en el negocio |
| `equivalencias`: sinónimos → valor válido; lo irreconocible = no declarado + aviso | `estado: "leve"` lanzaba `KeyError` |
| 14 razas comunes nuevas marcadas `SUPUESTO` | Validar con la propietaria |
| `preguntas_cliente` y `como_lo_describe_la_clienta` | Texto de las preguntas del agente, editable sin tocar código |

Pruebas: `tests/test_motor_v2.py` (las 39 originales + las de estos cambios).
