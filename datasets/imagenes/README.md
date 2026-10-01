# SCRUM-101 — Preparación y anonimización del dataset de imágenes

Proyecto MIA — Lina's Pet Salón · Épica SCRUM-100 (Agente de Cotización por Imagen)
Daniel Loza C. · 20 de septiembre de 2026

---

## Qué hay aquí

```
preparar_dataset.py          orquestador del pipeline (CLI)
generar_anexo.js             genera el anexo metodológico en Word
src/
  clases.py                  clases objetivo, tomadas del tarifario de SCRUM-98
  mapeo_razas.py             tabla de las 120 razas → tamaño y pelaje
  anonimizacion.py           limpieza de metadatos, seudonimización, pHash
  dataset.py                 manifiesto, partición y controles de fuga
  degradacion.py             aumentación que simula el canal de WhatsApp
  reporte.py                 cobertura, brecha y cálculo del n mínimo
config/
  mapeo_razas.csv            tabla generada (120 filas)
  etiquetas_plantilla.csv    plantilla que llena la propietaria
docs/
  protocolo_captura.md       instructivo de captura estructurada
  consentimiento_informado.md formulario conforme a la LOPDP
tests/
  test_scrum101.py           28 pruebas, nombradas por criterio de aceptación
```

---

## Cómo se ejecuta

```bash
pip install pillow imagehash

# La sal es la MISMA de SCRUM-63. No se versiona.
export MIA_SAL_SEUDONIMO='...'

# 1. Demostración reproducible, sin fotografías reales
python preparar_dataset.py --simular --salida datos/demo

# 2. Ejecución real, cuando lleguen las fotos
python preparar_dataset.py \
    --stanford  datos/crudo/stanford_dogs/Images \
    --instagram datos/crudo/propias/instagram \
    --captura   datos/crudo/propias/captura \
    --etiquetas datos/crudo/propias/etiquetas.csv \
    --tarifario ../../app/cotizacion/tarifario_v1.json \
    --salida    datos/procesado

# 3. Pruebas
python tests/test_scrum101.py
```

Salidas: `manifiesto.csv`, `reporte_cobertura.txt` y `reporte_cobertura.json`.
El manifiesto —no las carpetas— es el dataset.

---

## Las tres decisiones que hay que conocer antes de tocar nada

**1. La etiqueta de tamaño derivada de la raza es débil, no verdad de campo.**
Un Beagle pesa entre 9 y 11,3 kg y cruza el corte de 9,0 kg del tarifario. Las
razas cuyo rango cruza un corte se marcan ambiguas y no aportan etiqueta de
tamaño. Solo 70 de las 120 razas producen una etiqueta de tamaño utilizable.

**2. El conjunto de prueba es exclusivamente de dominio real.** Stanford Dogs
nunca llega a `test`. Medir el F1 de SCRUM-105 sobre imágenes de catálogo daría
un número alto y sin significado. El verificador de partición bloquea el cierre
si detecta contaminación.

**3. La partición agrupa por mascota, no por imagen.** Con ~12 clientes fijos, la
misma mascota aparece muchas veces; si sus fotos caen a ambos lados, el modelo
reconoce al individuo y la métrica se infla. Semilla 42, la misma de SCRUM-63.

---

## Hallazgos que salen del análisis

| Hallazgo | Cifra | A quién afecta |
|---|---|---|
| Razas con etiqueta de tamaño utilizable | 70 de 120 (58,3 %) | SCRUM-102 |
| Razas en la franja mediana (9,1–18 kg) | **6** | SCRUM-102, SCRUM-105 |
| Razas de pelaje rizado (factor 1,25) | **8** | SCRUM-102, SCRUM-105 |
| Razas de pelo duro sin categoría en el tarifario | 18 | **SCRUM-98** |
| Razas excluidas por superar los 45 kg | 19 | SCRUM-98 |
| Cánidos no domésticos en el dataset público | 3 | — |
| Fotografías propias para un IC 95 % de ±10 pts | **~490** | **SCRUM-105** |

Las dos filas en negrita son las que conviene llevar a la reunión: la franja
mediana y el pelaje rizado son las clases peor cubiertas, y el pelaje rizado es
además el de recargo más alto. Un fallo sistemático ahí produce cotizaciones por
debajo del costo, un error que no genera queja del cliente y puede pasar
inadvertido.

---

## Bloqueantes

1. **Fotografías propias del negocio.** Sin ellas no hay conjunto de prueba de
   dominio real y la métrica de SCRUM-105 no es defendible.
2. **Consentimiento informado firmado.** Revisar con un profesional del derecho
   antes de usarlo con clientes.
3. **`tarifario_v1.json`.** Para verificar automáticamente que los nombres de
   clase coinciden con los que consume el motor de cotización.
4. **Margen de error admisible de la métrica.** Decide cuántas fotografías hay
   que recoger. Debe decidirse antes de entrenar, no después de ver resultados.
5. **Quinta categoría de pelaje (pelo duro).** Decisión de la propietaria,
   pertenece a SCRUM-98.

---

## Advertencia para el informe de titulación

Ninguna cifra de este paquete es un resultado del proyecto. Son propiedades del
dataset público y cálculos de diseño. Los rangos de peso por raza provienen de
estándares de raza, no de mediciones del negocio. El dataset propio todavía no
existe.

Además, el acuerdo de acceso de ImageNet —del que Stanford Dogs deriva sus
imágenes— restringe el uso a investigación no comercial y educativa. El trabajo
de titulación queda dentro de ese alcance; un despliegue comercial, no.
