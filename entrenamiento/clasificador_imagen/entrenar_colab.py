"""
SCRUM-102 — Entrenamiento del clasificador de tamano y pelaje por transfer
learning. Pensado para Google Colab (GPU T4 del tier gratuito).

Arquitectura: EfficientNet-B0 preentrenada en ImageNet + dos cabezas
lineales independientes (tamano: 3 clases, pelaje: 4 clases), en linea con
la decision D1 de SCRUM-101 (dos variables, no una clase combinada).

Decisiones de entrenamiento:
- Perdida enmascarada: las imagenes con tamano ambiguo (raza cuyo rango de
  peso cruza un corte del tarifario) o fuera de rango NO aportan perdida de
  tamano, pero si de pelaje. Asi no se entrena con etiquetas debiles falsas.
- Pesos de clase inversos a la frecuencia: las clases mediano y rizado estan
  subrepresentadas (hallazgo de SCRUM-101).
- Aumentacion con la degradacion del canal de WhatsApp (degradacion.py de
  SCRUM-101), ademas de flips y recortes.
- Dos etapas: 1) backbone congelado, solo cabezas; 2) descongelar los
  ultimos bloques con tasa de aprendizaje menor.
- Seleccion del mejor epoch por F1 macro promedio en validacion.
- Calibracion por temperature scaling (Guo et al., 2017) sobre validacion:
  la politica de fallback de SCRUM-104 usa umbrales de confianza, que solo
  tienen sentido si las probabilidades estan calibradas.
- El conjunto de prueba (solo dominio real, regla de SCRUM-101) se evalua
  UNA vez al final; los numeros oficiales los consolida SCRUM-105.

Salida (copiar a app/vision/modelos/ del repo):
    clasificador_v1.onnx   modelo con salidas "tamano" y "pelaje" (logits)
    clasificador_v1.json   clases, temperatura, normalizacion, metricas

Uso en Colab:
    !pip install -q onnx onnxruntime scikit-learn
    !git clone <repo> && cd <repo>
    !python entrenamiento/clasificador_imagen/entrenar_colab.py \
        --manifiesto /content/drive/MyDrive/MIA/procesado/manifiesto.csv \
        --raiz-imagenes /content/drive/MyDrive/MIA/procesado \
        --salida /content/drive/MyDrive/MIA/modelos
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from sklearn.metrics import classification_report, f1_score
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms

RAIZ_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ_REPO / "datasets" / "imagenes"))
try:
    from src.degradacion import degradar  # SCRUM-101
except ImportError:  # pragma: no cover
    degradar = None

SEMILLA = 42  # misma semilla que SCRUM-63 y SCRUM-101
CLASES_TAMANO = ["pequeno", "mediano", "grande"]
CLASES_PELAJE = ["corto", "doble", "largo", "rizado"]  # vocabulario del dataset
MEDIA = [0.485, 0.456, 0.406]
DESV = [0.229, 0.224, 0.225]
LADO = 224
IGNORAR = -100


def fijar_semilla(s: int) -> None:
    random.seed(s)
    np.random.seed(s)
    torch.manual_seed(s)
    torch.cuda.manual_seed_all(s)


class DatasetMIA(Dataset):
    def __init__(self, filas: list[dict], raiz: Path, entrenamiento: bool):
        self.filas, self.raiz, self.entrenamiento = filas, raiz, entrenamiento
        self.rng = random.Random(SEMILLA)
        if entrenamiento:
            self.tf = transforms.Compose([
                transforms.RandomResizedCrop(LADO, scale=(0.6, 1.0)),
                transforms.RandomHorizontalFlip(),
                transforms.ColorJitter(0.2, 0.2, 0.1),
                transforms.ToTensor(),
                transforms.Normalize(MEDIA, DESV),
            ])
        else:
            # Debe coincidir con ClasificadorOnnx._preprocesar en app/vision.
            self.tf = transforms.Compose([
                transforms.Resize(int(LADO * 1.14)),
                transforms.CenterCrop(LADO),
                transforms.ToTensor(),
                transforms.Normalize(MEDIA, DESV),
            ])

    def __len__(self):
        return len(self.filas)

    def __getitem__(self, i):
        f = self.filas[i]
        img = Image.open(self.raiz / f["ruta"]).convert("RGB")
        if self.entrenamiento and degradar is not None and self.rng.random() < 0.5:
            img = degradar(img, self.rng)
        return self.tf(img), etiqueta_tamano(f), etiqueta_pelaje(f)


def etiqueta_tamano(f: dict) -> int:
    if f.get("tamano_ambiguo") == "1" or f.get("tamano") not in CLASES_TAMANO:
        return IGNORAR
    return CLASES_TAMANO.index(f["tamano"])


def etiqueta_pelaje(f: dict) -> int:
    return CLASES_PELAJE.index(f["pelaje"]) if f.get("pelaje") in CLASES_PELAJE else IGNORAR


class ClasificadorDosCabezas(nn.Module):
    def __init__(self):
        super().__init__()
        base = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.IMAGENET1K_V1)
        self.backbone = base.features
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.dropout = nn.Dropout(0.3)
        n = base.classifier[1].in_features
        self.cabeza_tamano = nn.Linear(n, len(CLASES_TAMANO))
        self.cabeza_pelaje = nn.Linear(n, len(CLASES_PELAJE))

    def forward(self, x):
        h = self.dropout(torch.flatten(self.pool(self.backbone(x)), 1))
        return self.cabeza_tamano(h), self.cabeza_pelaje(h)


def pesos_clase(etiquetas: list[int], n: int) -> torch.Tensor:
    conteo = np.bincount([e for e in etiquetas if e != IGNORAR], minlength=n).astype(float)
    conteo[conteo == 0] = 1
    w = conteo.sum() / (n * conteo)
    return torch.tensor(w, dtype=torch.float32)


@torch.no_grad()
def predecir(modelo, cargador, dispositivo):
    modelo.eval()
    lt, lp, yt, yp = [], [], [], []
    for x, t, p in cargador:
        a, b = modelo(x.to(dispositivo))
        lt.append(a.cpu()); lp.append(b.cpu()); yt.append(t); yp.append(p)
    return torch.cat(lt), torch.cat(lp), torch.cat(yt), torch.cat(yp)


def f1_macro(logits, y) -> float:
    m = y != IGNORAR
    if m.sum() == 0:
        return float("nan")
    return f1_score(y[m].numpy(), logits[m].argmax(1).numpy(), average="macro")


def ajustar_temperatura(logits, y) -> float:
    m = y != IGNORAR
    if m.sum() < 10:
        return 1.0  # muy pocos ejemplos para calibrar de forma fiable
    logits, y = logits[m], y[m]
    log_t = torch.zeros(1, requires_grad=True)
    opt = torch.optim.LBFGS([log_t], lr=0.05, max_iter=200)

    def cierre():
        opt.zero_grad()
        perdida = F.cross_entropy(logits / log_t.exp(), y)
        perdida.backward()
        return perdida

    opt.step(cierre)
    return float(log_t.exp().clamp(0.5, 5.0))


def entrenar_epoch(modelo, cargador, opt, crit_t, crit_p, dispositivo):
    modelo.train()
    total = 0.0
    for x, t, p in cargador:
        x, t, p = x.to(dispositivo), t.to(dispositivo), p.to(dispositivo)
        a, b = modelo(x)
        perdida = 0.0
        if (t != IGNORAR).any():
            perdida = perdida + crit_t(a, t)
        if (p != IGNORAR).any():
            perdida = perdida + crit_p(b, p)
        if isinstance(perdida, float):
            continue
        opt.zero_grad()
        perdida.backward()
        opt.step()
        total += perdida.item() * len(x)
    return total / len(cargador.dataset)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifiesto", required=True, type=Path)
    ap.add_argument("--raiz-imagenes", type=Path, help="por defecto, la carpeta del manifiesto")
    ap.add_argument("--salida", type=Path, default=Path("modelos"))
    ap.add_argument("--version", default="clasificador_v1")
    ap.add_argument("--epocas-cabezas", type=int, default=4)
    ap.add_argument("--epocas-ajuste", type=int, default=12)
    ap.add_argument("--lote", type=int, default=32)
    args = ap.parse_args()

    fijar_semilla(SEMILLA)
    dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
    raiz = args.raiz_imagenes or args.manifiesto.parent
    filas = list(csv.DictReader(open(args.manifiesto, encoding="utf-8")))
    part = {k: [f for f in filas if f["particion"] == k] for k in ("train", "val", "test")}
    print({k: len(v) for k, v in part.items()}, "| dispositivo:", dispositivo)
    if any(f["fuente"] == "stanford_dogs" for f in part["test"]):
        raise SystemExit("El conjunto de prueba contiene Stanford Dogs: regenerar la particion (SCRUM-101).")

    cargadores = {
        k: DataLoader(DatasetMIA(v, raiz, k == "train"), batch_size=args.lote,
                      shuffle=(k == "train"), num_workers=2)
        for k, v in part.items() if v
    }

    modelo = ClasificadorDosCabezas().to(dispositivo)
    crit_t = nn.CrossEntropyLoss(weight=pesos_clase([etiqueta_tamano(f) for f in part["train"]], 3).to(dispositivo),
                                 ignore_index=IGNORAR, label_smoothing=0.05)
    crit_p = nn.CrossEntropyLoss(weight=pesos_clase([etiqueta_pelaje(f) for f in part["train"]], 4).to(dispositivo),
                                 ignore_index=IGNORAR, label_smoothing=0.05)

    mejor = {"f1": -1.0, "estado": None, "epoca": None}

    def evaluar_y_guardar(epoca):
        if "val" not in cargadores:
            mejor.update(estado={k: v.detach().clone() for k, v in modelo.state_dict().items()}, epoca=epoca)
            return
        lt, lp, yt, yp = predecir(modelo, cargadores["val"], dispositivo)
        f1t, f1p = f1_macro(lt, yt), f1_macro(lp, yp)
        f1 = np.nanmean([f1t, f1p])
        print(f"  val F1 tamano={f1t:.3f} pelaje={f1p:.3f}")
        if f1 > mejor["f1"]:
            mejor.update(f1=f1, epoca=epoca,
                         estado={k: v.detach().clone() for k, v in modelo.state_dict().items()})

    # Etapa 1: backbone congelado
    for prm in modelo.backbone.parameters():
        prm.requires_grad = False
    opt = torch.optim.AdamW(filter(lambda p: p.requires_grad, modelo.parameters()), lr=1e-3, weight_decay=1e-4)
    for e in range(args.epocas_cabezas):
        t0 = time.time()
        print(f"[cabezas {e + 1}] perdida={entrenar_epoch(modelo, cargadores['train'], opt, crit_t, crit_p, dispositivo):.4f} ({time.time() - t0:.0f}s)")
        evaluar_y_guardar(f"cabezas_{e + 1}")

    # Etapa 2: descongelar los ultimos 3 bloques de EfficientNet
    for bloque in modelo.backbone[-3:]:
        for prm in bloque.parameters():
            prm.requires_grad = True
    opt = torch.optim.AdamW([
        {"params": [p for p in modelo.backbone.parameters() if p.requires_grad], "lr": 1e-4},
        {"params": list(modelo.cabeza_tamano.parameters()) + list(modelo.cabeza_pelaje.parameters()), "lr": 5e-4},
    ], weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epocas_ajuste)
    for e in range(args.epocas_ajuste):
        t0 = time.time()
        print(f"[ajuste {e + 1}] perdida={entrenar_epoch(modelo, cargadores['train'], opt, crit_t, crit_p, dispositivo):.4f} ({time.time() - t0:.0f}s)")
        sched.step()
        evaluar_y_guardar(f"ajuste_{e + 1}")

    modelo.load_state_dict(mejor["estado"])
    print("Mejor epoca:", mejor["epoca"])

    # Calibracion y metricas
    temperatura, metricas = {"tamano": 1.0, "pelaje": 1.0}, {"mejor_epoca": mejor["epoca"]}
    if "val" in cargadores:
        lt, lp, yt, yp = predecir(modelo, cargadores["val"], dispositivo)
        temperatura = {"tamano": ajustar_temperatura(lt, yt), "pelaje": ajustar_temperatura(lp, yp)}
        metricas["val"] = {"f1_macro_tamano": f1_macro(lt, yt), "f1_macro_pelaje": f1_macro(lp, yp)}
    if "test" in cargadores:
        lt, lp, yt, yp = predecir(modelo, cargadores["test"], dispositivo)
        metricas["test"] = {"f1_macro_tamano": f1_macro(lt, yt), "f1_macro_pelaje": f1_macro(lp, yp)}
        for nombre, lg, y, clases in (("tamano", lt, yt, CLASES_TAMANO), ("pelaje", lp, yp, CLASES_PELAJE)):
            m = y != IGNORAR
            if m.any():
                print(f"\nTEST {nombre}\n", classification_report(
                    y[m].numpy(), lg[m].argmax(1).numpy(), labels=list(range(len(clases))),
                    target_names=clases, zero_division=0))
    print("Temperaturas:", temperatura, "| Metricas:", metricas)

    # Exportacion
    args.salida.mkdir(parents=True, exist_ok=True)
    ruta_onnx = args.salida / f"{args.version}.onnx"
    modelo.eval().cpu()
    torch.onnx.export(
        modelo, torch.randn(1, 3, LADO, LADO), ruta_onnx,
        input_names=["imagen"], output_names=["tamano", "pelaje"],
        dynamic_axes={"imagen": {0: "lote"}, "tamano": {0: "lote"}, "pelaje": {0: "lote"}},
        opset_version=17,
    )
    meta = {
        "version": args.version,
        "arquitectura": "efficientnet_b0 + 2 cabezas",
        "clases_tamano": CLASES_TAMANO,
        "clases_pelaje": CLASES_PELAJE,
        "tamano_entrada": LADO, "media": MEDIA, "desv": DESV,
        "temperatura": temperatura,
        "metricas": metricas,
        "particiones": {k: len(v) for k, v in part.items()},
        "semilla": SEMILLA,
        "entrenado": time.strftime("%Y-%m-%d %H:%M"),
    }
    (args.salida / f"{args.version}.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Exportado:", ruta_onnx)


if __name__ == "__main__":
    main()
