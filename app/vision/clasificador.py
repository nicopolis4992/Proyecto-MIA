"""
Clasificador de tamano, grupo de manto y estado del pelo a partir de una foto (SCRUM-102).

Dos implementaciones con la misma salida (`Clasificacion`), en el
vocabulario del tarifario v2 (SCRUM-98): tamano, grupo de manto (A-D) y
estado del manto. Predicen por apariencia, no por raza, asi que funcionan
igual con mestizos:

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

TAMANOS = ("pequeno", "mediano", "grande")
GRUPOS = ("A_maquina", "B_deslanado", "C_cepillado", "D_corto")
ESTADOS = ("sin_motas", "moderado", "severo")


@dataclass
class Clasificacion:
    es_perro: bool
    tamano: str | None
    confianza_tamano: float
    grupo: str | None
    confianza_grupo: float
    backend: str
    version: str
    estado: str | None = None
    confianza_estado: float = 0.0
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
        self.clases_grupo = self.meta["clases_grupo"]
        self.clases_estado = self.meta.get("clases_estado")  # cabeza opcional
        self.salidas = [o.name for o in self.sesion.get_outputs()]

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
        salidas = self.sesion.run(self.salidas, {self.entrada: self._preprocesar(datos)})
        logits = dict(zip(self.salidas, salidas))
        temp = self.meta.get("temperatura", {})
        probs, mejor = {}, {}
        for cabeza, clases in (("tamano", self.clases_tamano), ("grupo", self.clases_grupo),
                               ("estado", self.clases_estado)):
            if clases is None or cabeza not in logits:
                continue
            p = _softmax(logits[cabeza][0], temp.get(cabeza, 1.0))
            i = int(p.argmax())
            mejor[cabeza] = (clases[i], float(p[i]))
            probs[cabeza] = dict(zip(clases, map(float, p.round(4))))
        estado, conf_estado = mejor.get("estado", (None, 0.0))
        return Clasificacion(
            es_perro=True,  # la CNN no detecta "no perro": lo cubre la baja confianza
            tamano=mejor["tamano"][0], confianza_tamano=mejor["tamano"][1],
            grupo=mejor["grupo"][0], confianza_grupo=mejor["grupo"][1],
            estado=estado, confianza_estado=conf_estado,
            backend="cnn_onnx", version=self.meta.get("version", "desconocida"),
            probabilidades=probs,
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
- grupo (tipo de manto, segun como se trabaja en la peluqueria):
  "A_maquina": pelo largo de crecimiento continuo que se corta con maquina
    (shih tzu, schnauzer, poodle, yorkie, maltes y sus mestizos).
  "B_deslanado": doble capa con subpelo denso, no se pasa maquina
    (husky, pug, labrador, pastor aleman, pomerania).
  "C_cepillado": pelo largo sin maquina, mucho cepillado y corte a tijera
    (golden, border collie).
  "D_corto": pelo corto pegado al cuerpo (chihuahua de pelo corto, pitbull,
    rottweiler, mestizos de pelo corto).
- estado: "sin_motas" (pelo suelto y limpio), "moderado" (algunos nudos o
  zonas apelmazadas), "severo" (muy enredado o apelmazado en gran parte).
- confianza_tamano, confianza_grupo y confianza_estado entre 0 y 1. Usa
  valores bajos si la foto no muestra el cuerpo completo, no hay referencia
  de escala, el perro esta lejos o mojado, o el pelo esta recien cortado.
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
                "grupo": types.Schema(type=types.Type.STRING, enum=list(GRUPOS)),
                "confianza_grupo": types.Schema(type=types.Type.NUMBER),
                "estado": types.Schema(type=types.Type.STRING, enum=list(ESTADOS)),
                "confianza_estado": types.Schema(type=types.Type.NUMBER),
                "observacion": types.Schema(type=types.Type.STRING, nullable=True),
            },
            required=["es_perro", "num_perros", "tamano", "confianza_tamano", "grupo",
                      "confianza_grupo", "estado", "confianza_estado", "observacion"],
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
            grupo=d["grupo"], confianza_grupo=float(d["confianza_grupo"]),
            estado=d["estado"], confianza_estado=float(d["confianza_estado"]),
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
