"""
Clasificador de tamano y tipo de pelaje a partir de una foto (SCRUM-102).

Dos implementaciones con la misma salida (`Clasificacion`), en el
vocabulario del tarifario (SCRUM-98), no en el del dataset:

- ClasificadorOnnx: la CNN ajustada por transfer learning en Colab
  (entrenamiento/clasificador_imagen/entrenar_colab.py), exportada a ONNX
  con su archivo de metadatos (clases, temperatura de calibracion, version).
  Es el clasificador objetivo del proyecto.
- ClasificadorGemini: linea base zero-shot con Gemini multimodal. Permite
  que el prototipo cotice por foto mientras la CNN no este entrenada, y sirve
  de punto de comparacion en SCRUM-105. Su "confianza" es autodeclarada por
  el modelo y NO esta calibrada: por eso la politica de fallback le exige
  umbrales mas altos (ver politica_imagen.json).

`crear_clasificador()` usa la CNN si existe el modelo; si no, Gemini.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.vision.calidad import cargar_imagen

logger = logging.getLogger("vision")

DIR_MODELOS = Path(__file__).parent / "modelos"
RUTA_ONNX = Path(os.getenv("VISION_MODELO_ONNX", DIR_MODELOS / "clasificador_v1.onnx"))

# El dataset de SCRUM-101 usa "doble" para el pelaje de doble capa; el
# tarifario usa "doble_capa". La traduccion vive solo aqui.
PELAJE_DATASET_A_TARIFARIO = {"doble": "doble_capa"}
TAMANOS = ("pequeno", "mediano", "grande")
PELAJES = ("corto", "largo", "rizado", "doble_capa")


@dataclass
class Clasificacion:
    es_perro: bool
    tamano: str | None
    confianza_tamano: float
    pelaje: str | None
    confianza_pelaje: float
    backend: str
    version: str
    probabilidades: dict = field(default_factory=dict)
    observacion: str | None = None


# ---------------------------------------------------------------------------
# CNN (ONNX)
# ---------------------------------------------------------------------------

def _softmax(z: np.ndarray, temperatura: float) -> np.ndarray:
    z = z / temperatura
    z = z - z.max()
    e = np.exp(z)
    return e / e.sum()


class ClasificadorOnnx:
    def __init__(self, ruta_modelo: Path = RUTA_ONNX):
        import onnxruntime as ort  # dependencia solo necesaria con este backend

        self.sesion = ort.InferenceSession(str(ruta_modelo), providers=["CPUExecutionProvider"])
        self.meta = json.loads(Path(ruta_modelo).with_suffix(".json").read_text(encoding="utf-8"))
        self.entrada = self.sesion.get_inputs()[0].name
        self.clases_tamano = self.meta["clases_tamano"]
        self.clases_pelaje = [PELAJE_DATASET_A_TARIFARIO.get(c, c) for c in self.meta["clases_pelaje"]]

    def _preprocesar(self, datos: bytes) -> np.ndarray:
        lado = self.meta.get("tamano_entrada", 224)
        img = cargar_imagen(datos)
        # Mismo preprocesamiento que la validacion en entrenamiento:
        # resize del lado menor a lado*1.14 y recorte central.
        escala = int(lado * 1.14)
        w, h = img.size
        r = escala / min(w, h)
        img = img.resize((round(w * r), round(h * r)))
        w, h = img.size
        izq, arr = (w - lado) // 2, (h - lado) // 2
        img = img.crop((izq, arr, izq + lado, arr + lado))
        a = np.asarray(img, dtype=np.float32) / 255.0
        a = (a - np.array(self.meta["media"], dtype=np.float32)) / np.array(self.meta["desv"], dtype=np.float32)
        return a.transpose(2, 0, 1)[None]

    def clasificar(self, datos: bytes) -> Clasificacion:
        logits_t, logits_p = self.sesion.run(["tamano", "pelaje"], {self.entrada: self._preprocesar(datos)})
        temp = self.meta.get("temperatura", {})
        p_t = _softmax(logits_t[0], temp.get("tamano", 1.0))
        p_p = _softmax(logits_p[0], temp.get("pelaje", 1.0))
        it, ip = int(p_t.argmax()), int(p_p.argmax())
        return Clasificacion(
            es_perro=True,  # la CNN no detecta "no perro": lo cubre la baja confianza
            tamano=self.clases_tamano[it], confianza_tamano=float(p_t[it]),
            pelaje=self.clases_pelaje[ip], confianza_pelaje=float(p_p[ip]),
            backend="cnn_onnx", version=self.meta.get("version", "desconocida"),
            probabilidades={
                "tamano": dict(zip(self.clases_tamano, map(float, p_t.round(4)))),
                "pelaje": dict(zip(self.clases_pelaje, map(float, p_p.round(4)))),
            },
        )


# ---------------------------------------------------------------------------
# Linea base: Gemini multimodal zero-shot
# ---------------------------------------------------------------------------

PROMPT_VISION = """Analiza la foto enviada por un cliente de una peluqueria canina.
Devuelve:
- es_perro: true solo si se ve claramente al menos un perro.
- num_perros: cuantos perros se ven.
- tamano: estimacion del tamano del perro principal segun su peso adulto aparente:
  "pequeno" (hasta 9 kg), "mediano" (9 a 18 kg), "grande" (18 a 45 kg).
- pelaje: "corto" (pelo corto y liso), "largo" (pelo largo y liso o sedoso),
  "rizado" (rizado o lanoso, tipo poodle o bichon), "doble_capa" (manto denso
  con subpelo, tipo husky, pastor aleman, golden, pomerania).
- confianza_tamano y confianza_pelaje entre 0 y 1. Usa valores bajos si la
  foto no muestra el cuerpo completo, no hay referencia de escala, el perro
  esta lejos o mojado, o el pelaje esta recien cortado.
- observacion: una frase corta solo si hay algo relevante (ej. nudos visibles,
  foto de cachorro, varios perros). Si no, null.
No identifiques la raza ni opines sobre la salud del animal."""


class ClasificadorGemini:
    def __init__(self, client, modelo: str | None = None):
        from app.config import MODELO_VISION

        self.client = client
        self.modelo = modelo or MODELO_VISION

    def clasificar(self, datos: bytes) -> Clasificacion:
        from google.genai import types

        esquema = types.Schema(
            type=types.Type.OBJECT,
            properties={
                "es_perro": types.Schema(type=types.Type.BOOLEAN),
                "num_perros": types.Schema(type=types.Type.INTEGER),
                "tamano": types.Schema(type=types.Type.STRING, enum=list(TAMANOS)),
                "confianza_tamano": types.Schema(type=types.Type.NUMBER),
                "pelaje": types.Schema(type=types.Type.STRING, enum=list(PELAJES)),
                "confianza_pelaje": types.Schema(type=types.Type.NUMBER),
                "observacion": types.Schema(type=types.Type.STRING, nullable=True),
            },
            required=["es_perro", "num_perros", "tamano", "confianza_tamano",
                      "pelaje", "confianza_pelaje", "observacion"],
        )
        mime = "image/png" if datos[:4] == b"\x89PNG" else "image/jpeg"
        resp = self.client.models.generate_content(
            model=self.modelo,
            contents=[types.Part.from_bytes(data=datos, mime_type=mime), PROMPT_VISION],
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=esquema, temperature=0.0
            ),
        )
        d = json.loads(resp.text)
        return Clasificacion(
            es_perro=bool(d["es_perro"]) and d.get("num_perros", 1) >= 1,
            tamano=d["tamano"], confianza_tamano=float(d["confianza_tamano"]),
            pelaje=d["pelaje"], confianza_pelaje=float(d["confianza_pelaje"]),
            backend="gemini_zero_shot", version=self.modelo,
            observacion=d.get("observacion"),
            probabilidades={"num_perros": d.get("num_perros")},
        )


def crear_clasificador(client=None):
    backend = os.getenv("VISION_BACKEND", "auto")
    if backend in ("auto", "cnn") and RUTA_ONNX.exists():
        try:
            return ClasificadorOnnx(RUTA_ONNX)
        except ImportError:
            if backend == "cnn":
                raise
            logger.warning("Modelo ONNX presente pero falta onnxruntime; uso Gemini.")
    if client is None:
        from app.config import crear_cliente_gemini

        client = crear_cliente_gemini()
    return ClasificadorGemini(client)
