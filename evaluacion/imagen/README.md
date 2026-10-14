# SCRUM-105 — Clasificador de imagen: CNN frente a Gemini

Las mismas 48 fotos de prueba (partición estratificada por mascota, semilla 42).

| Cabeza | CNN EfficientNet-B0 (F1 macro, IC 95 %) | Gemini sin entrenamiento |
|---|---|---|
| Tamaño | 0,477 [0,28–0,67] | 0,979 |
| Grupo de manto | 0,620 [0,30–0,84] | 1,000 |
| Estado del pelo | 0,387 [0,23–0,50] | 0,491 |

**Las cifras de Gemini en tamaño y grupo no son una medición válida.** Las etiquetas se
pre-propusieron con Gemini, y la revisión humana casi no cambió esas dos variables
(0 tamaños y 2 grupos de 289), así que Gemini se evalúa en parte contra sí mismo y la
CNN aprende a imitarlo. El estado sí se corrigió (89 de 289 etiquetas) y es la
comparación más honesta: los dos quedan por debajo de 0,85.

**Grad-CAM (CNN):** en varias fotos la cabeza de estado mira la pañoleta o el lazo, y
la de grupo mira el fondo cuando se equivoca. Es un atajo: las fotos "después"
llevan accesorio y están sin nudos.

**Siguiente paso:** etiquetado ciego de las 48 fotos por la propietaria (estándar de
oro independiente) para comparar ambos modelos de forma válida:

    python -m entrenamiento.clasificador_imagen.revisar --ciego
    python -m evaluacion.imagen.comparar_cnn_gemini --predicciones-cnn READ/modelo/clasificador_v1_predicciones_test.csv         --imagenes READ/para_colab/dataset --solo-lectura --estandar-oro READ/estandar_oro_propietaria.csv

El modo ciego muestra solo la foto: sin propuestas, sin nombre de la mascota y sin
"antes/después" (que insinúa el estado). La comparación reporta además cuánto
coinciden las etiquetas del equipo con las de la propietaria.

Archivos: `resultados/cnn_vs_gemini.json` y `resultados/cnn_vs_gemini_detalle.csv`;
métricas del entrenamiento en `resultados/cnn_clasificador_v1_metricas.json`.
Repetir sin gastar créditos:
`python -m evaluacion.imagen.comparar_cnn_gemini --predicciones-cnn <csv> --imagenes <carpeta> --solo-lectura`
