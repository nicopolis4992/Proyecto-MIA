# SCRUM-102 — Entrenamiento del clasificador (Colab)

1. Subir a Google Drive la salida del pipeline de SCRUM-101
   (`manifiesto.csv` + carpetas de imágenes de `datos/procesado`).
2. En Colab (Entorno de ejecución → GPU T4):
   ```
   !pip install -q onnx onnxruntime scikit-learn
   from google.colab import drive; drive.mount('/content/drive')
   !git clone <url-del-repo> mia && cd mia && python entrenamiento/clasificador_imagen/entrenar_colab.py \
       --manifiesto /content/drive/MyDrive/MIA/procesado/manifiesto.csv \
       --salida /content/drive/MyDrive/MIA/modelos
   ```
3. Copiar `clasificador_v1.onnx` y `clasificador_v1.json` a `app/vision/modelos/`
   y agregar `onnxruntime` a `requirements.txt`. El backend se activa solo
   (`VISION_BACKEND=auto` prefiere la CNN si el archivo existe).
4. Recalibrar `umbrales_confianza.cnn_onnx` en
   `app/cotizacion/politica_imagen.json` con la curva cobertura/precisión en
   validación (SCRUM-104) y entregar `clasificador_v1.json` a SCRUM-105.

Mientras la CNN no esté entrenada, el prototipo usa la línea base
`gemini_zero_shot` (ver `app/vision/clasificador.py`), que también sirve como
punto de comparación en SCRUM-105.
