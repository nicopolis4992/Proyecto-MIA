# Entregables Sprint 3 — SCRUM-63 y SCRUM-98

**Proyecto MIA — Lina's Pet Salón** · Responsable: Daniel Loza · Septiembre 2026

Documentación metodológica completa: `Anexo_Metodologico_SCRUM63_SCRUM98.docx`

> **Los valores numéricos de ambos entregables son provisionales.** El corpus es
> sintético y los precios son referencias de mercado de Quito, no los de la
> propietaria. La estructura sí es definitiva. Ver sección 6 del anexo.

---

## SCRUM-63 — Dataset de NLU

```bash
cd datasets/nlu
python3 build_dataset.py     # reconstruye el dataset y la partición
python3 baseline_nlu.py      # línea base y control de fuga entre particiones
```

| Archivo | Qué es |
|---|---|
| `corpus_semilla.py` | 278 enunciados etiquetados con intención y entidades |
| `guia_anotacion.md` | Reglas R1–R7, entidades y protocolo de kappa de Cohen |
| `anonimizador.py` | Seudonimización HMAC-SHA256 del export de WhatsApp |
| `build_dataset.py` | Deduplicación, partición estratificada 80/20, export CSV/JSONL |
| `baseline_nlu.py` | TF-IDF + regresión logística, matriz de confusión, control de fuga |
| `dataset_nlu_*.csv` · `.jsonl` | Salidas: 278 / 222 train / 56 test |

Cuando llegue el export real de WhatsApp:

```bash
export MIA_SALT="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"   # una sola vez
python3 anonimizador.py --entrada datos_crudos/chat.txt --salida corpus_anonimizado.csv \
        --propietaria "<nombre de la propietaria>"
# anotar la columna 'intencion' siguiendo guia_anotacion.md, luego:
python3 build_dataset.py --corpus-real corpus_anonimizado.csv
python3 baseline_nlu.py   # estas métricas sí son reportables
```

**Guarde la sal fuera del repositorio y destrúyala al cierre del proyecto.**
Ese paso es el que convierte la seudonimización en anonimización.

---

## SCRUM-98 — Tarifario parametrizado

```bash
# desde la raíz del proyecto
python -m app.cotizacion.motor_cotizacion                     # cuatro casos de demostración
python -m pytest tests/test_motor_cotizacion.py -v     # 29 pruebas
```

| Archivo | Qué es |
|---|---|
| `tarifario_v1.json` | Todos los valores del negocio. **Único archivo que se edita para cambiar precios.** |
| `motor_cotizacion.py` | Motor de cálculo, banda de confianza, validación de pico y placa |
| `test_motor_cotizacion.py` | 29 pruebas nombradas por criterio de aceptación |

Uso desde el agente de agenda:

```python
from app.cotizacion.motor_cotizacion import Motor, Mascota, Solicitud

motor = Motor("app/cotizacion/tarifario_v1.json")
cotizacion = motor.cotizar(Solicitud(
    mascotas=[Mascota(servicio="bano_corte", tamano="pequeno", pelaje="largo",
                      estado_manto="sin_nudos", comportamiento_conocido=True)],
    modalidad="puerta_a_puerta", zona="zona_1",
    fecha_hora=datetime(2026, 9, 17, 11, 0),
    cliente_recurrente=True,
))
# -> alimenta el campo cotizacion_estimada de SCRUM-74
```

---

## Pendientes que bloquean el cierre de ambas historias

1. Export del historial de WhatsApp Business (sin multimedia).
2. Sesión de validación de precios con la propietaria.
3. Último dígito de la placa del vehículo del servicio puerta a puerta.
4. Régimen tributario del negocio (define si el IVA aplica).
5. Doble anotación del 20 % del corpus real y cálculo de kappa (κ ≥ 0,80).
