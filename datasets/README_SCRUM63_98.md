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

**Versión vigente: v2** (precios de la propietaria, 04/10/2026), en
`app/cotizacion/tarifario_v2.json` + `motor_cotizacion_v2.py`. Cambios al
integrarlo y cómo se usa: `app/cotizacion/LEEME_tarifario_v2.md`.

```bash
python -m pytest tests/test_motor_v2.py -v
```

Los agentes no llaman al motor directamente sino a `app/cotizacion/cotizador.py`.

La versión v1 (precios de referencia del mercado) quedó en `archivo/tarifario_v1/`
como evidencia histórica; ya no la usa el sistema.

---

## Pendientes que bloquean el cierre de ambas historias

1. Export del historial de WhatsApp Business (sin multimedia).
2. Sesión de validación de precios con la propietaria.
3. Último dígito de la placa del vehículo del servicio puerta a puerta.
4. Régimen tributario del negocio (define si el IVA aplica).
5. Doble anotación del 20 % del corpus real y cálculo de kappa (κ ≥ 0,80).
