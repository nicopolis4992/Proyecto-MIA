"""
SCRUM-102 — Entrenamiento del clasificador de tamano, grupo de manto y estado por transfer
learning. Pensado para Google Colab (GPU T4 del tier gratuito).

Arquitectura: EfficientNet-B0 preentrenada en ImageNet + cabezas lineales
independientes, en el vocabulario del tarifario v2 (SCRUM-98):
  - tamano: pequeno / mediano / grande
  - grupo de manto: A_maquina / B_deslanado / C_cepillado / D_corto
  - estado del manto (opcional, si el manifiesto trae la columna `estado`):
    sin_motas / moderado / severo. Las fotos ANTES del dataset de Facebook
    son las que mejor lo muestran.
Decision D1 de SCRUM-101: variables separadas, no una clase combinada.
El clasificador predice por apariencia, no por raza: funciona con mestizos.

Columnas esperadas en el manifiesto: ruta, particion, fuente, tamano,
tamano_ambiguo, grupo y (opcional) estado. Etiquetas vacias se ignoran.

Decisiones de entrenamiento:
- Perdida enmascarada: las imagenes con tamano ambiguo (raza cuyo rango de
  peso cruza un corte del tarifario) o fuera de rango NO aportan perdida de
  tamano, pero si de grupo y estado. Asi no se entrena con etiquetas debiles falsas.
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
    clasificador_v1.onnx   modelo con salidas "tamano", "grupo" y "estado" (logits)
    clasificador_v1.json   clases, temperatura, normalizacion, metricas (F1 macro,
                           por clase, matriz de confusion e IC 95 % por bootstrap)
Ademas, para la evaluacion de SCRUM-105 (no se copian a la app):
    clasificador_v1_predicciones_test.csv   real / predicho / probabilidad por foto
    gradcam/                                mapas de atencion y su energia de borde

Uso en Colab:
    !pip install -q onnx onnxscript onnxruntime scikit-learn matplotlib
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
CLASES_GRUPO = ["A_maquina", "B_deslanado", "C_cepillado", "D_corto"]  # tarifario v2
CLASES_ESTADO = ["sin_motas", "moderado", "severo"]
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
        return self.tf(img), etiqueta_tamano(f), etiqueta_grupo(f), etiqueta_estado(f)


def etiqueta_tamano(f: dict) -> int:
    if f.get("tamano_ambiguo") == "1" or f.get("tamano") not in CLASES_TAMANO:
        return IGNORAR
    return CLASES_TAMANO.index(f["tamano"])


def etiqueta_grupo(f: dict) -> int:
    return CLASES_GRUPO.index(f["grupo"]) if f.get("grupo") in CLASES_GRUPO else IGNORAR


def etiqueta_estado(f: dict) -> int:
    return CLASES_ESTADO.index(f["estado"]) if f.get("estado") in CLASES_ESTADO else IGNORAR


class ClasificadorMultiCabeza(nn.Module):
    def __init__(self):
        super().__init__()
        base = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.IMAGENET1K_V1)
        self.backbone = base.features
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.dropout = nn.Dropout(0.3)
        n = base.classifier[1].in_features
        self.cabeza_tamano = nn.Linear(n, len(CLASES_TAMANO))
        self.cabeza_grupo = nn.Linear(n, len(CLASES_GRUPO))
        self.cabeza_estado = nn.Linear(n, len(CLASES_ESTADO))

    def forward(self, x):
        h = self.dropout(torch.flatten(self.pool(self.backbone(x)), 1))
        return self.cabeza_tamano(h), self.cabeza_grupo(h), self.cabeza_estado(h)


def pesos_clase(etiquetas: list[int], n: int) -> torch.Tensor:
    conteo = np.bincount([e for e in etiquetas if e != IGNORAR], minlength=n).astype(float)
    conteo[conteo == 0] = 1
    w = conteo.sum() / (n * conteo)
    return torch.tensor(w, dtype=torch.float32)


@torch.no_grad()
def predecir(modelo, cargador, dispositivo):
    modelo.eval()
    logits, etiquetas = [[], [], []], [[], [], []]
    for x, *ys in cargador:
        for i, salida in enumerate(modelo(x.to(dispositivo))):
            logits[i].append(salida.cpu())
            etiquetas[i].append(ys[i])
    return [torch.cat(l) for l in logits], [torch.cat(y) for y in etiquetas]


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


def metricas_por_clase(cabezas, logits, ys, n_boot: int = 1000) -> dict:
    """Precision, recall, F1 y soporte por clase, matriz de confusion e IC 95 % del F1 macro."""
    from sklearn.metrics import confusion_matrix

    rng = np.random.default_rng(SEMILLA)
    salida = {}
    for (nombre, clases, _), lg, y in zip(cabezas, logits, ys):
        m = (y != IGNORAR).numpy()
        if not m.any():
            continue
        real, pred = y.numpy()[m], lg.argmax(1).numpy()[m]
        etiquetas = list(range(len(clases)))
        rep = classification_report(real, pred, labels=etiquetas, target_names=clases,
                                    output_dict=True, zero_division=0)
        boot = []
        for _ in range(n_boot):
            idx = rng.integers(0, len(real), len(real))
            boot.append(f1_score(real[idx], pred[idx], labels=etiquetas, average="macro", zero_division=0))
        salida[nombre] = {
            "por_clase": {c: {k: round(float(v), 3) for k, v in rep[c].items()} for c in clases},
            "f1_macro": round(float(rep["macro avg"]["f1-score"]), 3),
            "f1_macro_ic95": [round(float(np.percentile(boot, 2.5)), 3), round(float(np.percentile(boot, 97.5)), 3)],
            "exactitud": round(float((real == pred).mean()), 3),
            "n": int(m.sum()),
            "matriz_confusion": {"clases": clases,
                                 "matriz": confusion_matrix(real, pred, labels=etiquetas).tolist()},
        }
    return salida


def guardar_predicciones(ruta: Path, filas: list[dict], cabezas, logits, temperatura: dict) -> None:
    """Una fila por imagen: etiqueta real, prediccion y probabilidad calibrada por cabeza.
    Sirve para comparar con la linea base de Gemini sobre las MISMAS imagenes (SCRUM-105)."""
    campos = ["ruta", "mascota_id"]
    for n, _, _ in cabezas:
        campos += [f"{n}_real", f"{n}_pred", f"{n}_prob"]
    with open(ruta, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        for i, f in enumerate(filas):
            fila = {"ruta": f["ruta"], "mascota_id": f.get("mascota_id", "")}
            for (n, clases, _), lg in zip(cabezas, logits):
                p = F.softmax(lg[i] / temperatura.get(n, 1.0), dim=0)
                fila.update({f"{n}_real": f.get(n, ""), f"{n}_pred": clases[int(p.argmax())],
                             f"{n}_prob": round(float(p.max()), 3)})
            w.writerow(fila)
    print("Predicciones de prueba:", ruta)


def mapa_gradcam(modelo, x, cabeza: int) -> tuple[np.ndarray, int]:
    """Grad-CAM (Selvaraju et al., 2017) sobre el ultimo mapa de rasgos del backbone,
    para la clase predicha por la cabeza indicada. Devuelve el mapa 224x224 en [0, 1]."""
    modelo.eval()
    x = x.clone().requires_grad_(True)  # por si el backbone quedo congelado
    rasgos = modelo.backbone(x)
    rasgos.retain_grad()
    h = torch.flatten(modelo.pool(rasgos), 1)
    salida = (modelo.cabeza_tamano, modelo.cabeza_grupo, modelo.cabeza_estado)[cabeza](h)
    clase = int(salida.argmax(1))
    modelo.zero_grad()
    salida[0, clase].backward()
    pesos = rasgos.grad.mean(dim=(2, 3), keepdim=True)
    cam = F.relu((pesos * rasgos).sum(1, keepdim=True))
    cam = F.interpolate(cam, size=(LADO, LADO), mode="bilinear", align_corners=False)[0, 0]
    cam = cam - cam.min()
    return (cam / (cam.max() + 1e-8)).detach().cpu().numpy(), clase


def _superponer(img: Image.Image, cam: np.ndarray) -> Image.Image:
    try:
        from matplotlib import colormaps
        color = (colormaps["jet"](cam)[..., :3] * 255).astype(np.uint8)
    except Exception:  # pragma: no cover - sin matplotlib: mapa en rojo
        color = np.stack([cam * 255, np.zeros_like(cam), np.zeros_like(cam)], -1).astype(np.uint8)
    return Image.blend(img, Image.fromarray(color), 0.45)


def generar_gradcam(modelo, filas: list[dict], raiz: Path, carpeta: Path, dispositivo) -> dict:
    """
    Guarda una imagen por foto (original + mapa de grupo + mapa de estado) y mide
    que parte de la atencion cae en el BORDE de la foto (franja exterior del 15 %),
    donde estan el marco y el logo de la plantilla de Facebook. Una energia de
    borde alta es senal de atajo y hay que revisar esas fotos a mano.
    """
    carpeta.mkdir(parents=True, exist_ok=True)
    prep = DatasetMIA([], raiz, entrenamiento=False).tf
    recorte = transforms.Compose([transforms.Resize(int(LADO * 1.14)), transforms.CenterCrop(LADO)])
    banda = int(LADO * 0.15)
    borde = np.ones((LADO, LADO), dtype=bool)
    borde[banda:-banda, banda:-banda] = False
    modelo.to(dispositivo)
    energias = {"grupo": [], "estado": []}
    resumen = []
    for f in filas:
        img = recorte(Image.open(raiz / f["ruta"]).convert("RGB"))
        x = prep(Image.open(raiz / f["ruta"]).convert("RGB")).unsqueeze(0).to(dispositivo)
        paneles = [img]
        for nombre, cabeza, clases in (("grupo", 1, CLASES_GRUPO), ("estado", 2, CLASES_ESTADO)):
            cam, clase = mapa_gradcam(modelo, x, cabeza)
            energia = float(cam[borde].sum() / (cam.sum() + 1e-8))
            energias[nombre].append(energia)
            paneles.append(_superponer(img, cam))
            resumen.append({"ruta": f["ruta"], "cabeza": nombre, "pred": clases[clase],
                            "real": f.get(nombre, ""), "energia_borde": round(energia, 3)})
        lienzo = Image.new("RGB", (LADO * len(paneles), LADO))
        for i, p in enumerate(paneles):
            lienzo.paste(p, (i * LADO, 0))
        lienzo.save(carpeta / (Path(f["ruta"]).stem + "_gradcam.jpg"), quality=85)
    with open(carpeta / "gradcam_resumen.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["ruta", "cabeza", "pred", "real", "energia_borde"])
        w.writeheader()
        w.writerows(resumen)
    # La franja del 15 % ocupa el 51 % del area: con atencion uniforme la energia de borde seria ~0,51.
    area_borde = float(borde.mean())
    return {
        "imagenes": len(filas),
        "area_borde": round(area_borde, 3),
        **{f"energia_borde_media_{n}": round(float(np.mean(v)), 3) for n, v in energias.items() if v},
        **{f"fotos_con_atajo_probable_{n}": int(sum(e > area_borde for e in v)) for n, v in energias.items() if v},
        "carpeta": str(carpeta),
    }


def entrenar_epoch(modelo, cargador, opt, criterios, dispositivo):
    modelo.train()
    total = 0.0
    for x, *ys in cargador:
        x = x.to(dispositivo)
        perdida = 0.0
        for salida, y, crit in zip(modelo(x), ys, criterios):
            y = y.to(dispositivo)
            if (y != IGNORAR).any():  # perdida enmascarada por cabeza
                perdida = perdida + crit(salida, y)
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
    ap.add_argument("--gradcam", type=int, default=60, help="imagenes de prueba con Grad-CAM (0 = no generar)")
    args = ap.parse_args()
    args.salida.mkdir(parents=True, exist_ok=True)

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

    modelo = ClasificadorMultiCabeza().to(dispositivo)
    cabezas = [("tamano", CLASES_TAMANO, etiqueta_tamano), ("grupo", CLASES_GRUPO, etiqueta_grupo),
               ("estado", CLASES_ESTADO, etiqueta_estado)]
    criterios = [
        nn.CrossEntropyLoss(weight=pesos_clase([fn(f) for f in part["train"]], len(clases)).to(dispositivo),
                            ignore_index=IGNORAR, label_smoothing=0.05)
        for _, clases, fn in cabezas
    ]
    con_estado = any(etiqueta_estado(f) != IGNORAR for f in part["train"])

    mejor = {"f1": -1.0, "estado": None, "epoca": None}

    def evaluar_y_guardar(epoca):
        if "val" not in cargadores:
            mejor.update(estado={k: v.detach().clone() for k, v in modelo.state_dict().items()}, epoca=epoca)
            return
        logits, ys = predecir(modelo, cargadores["val"], dispositivo)
        f1s = [f1_macro(l, y) for l, y in zip(logits, ys)]
        print("  val F1 " + " ".join(f"{n}={v:.3f}" for (n, _, _), v in zip(cabezas, f1s)))
        f1 = np.nanmean(f1s)
        if f1 > mejor["f1"]:
            mejor.update(f1=f1, epoca=epoca,
                         estado={k: v.detach().clone() for k, v in modelo.state_dict().items()})

    # Etapa 1: backbone congelado
    for prm in modelo.backbone.parameters():
        prm.requires_grad = False
    opt = torch.optim.AdamW(filter(lambda p: p.requires_grad, modelo.parameters()), lr=1e-3, weight_decay=1e-4)
    for e in range(args.epocas_cabezas):
        t0 = time.time()
        print(f"[cabezas {e + 1}] perdida={entrenar_epoch(modelo, cargadores['train'], opt, criterios, dispositivo):.4f} ({time.time() - t0:.0f}s)")
        evaluar_y_guardar(f"cabezas_{e + 1}")

    # Etapa 2: descongelar los ultimos 3 bloques de EfficientNet
    for bloque in modelo.backbone[-3:]:
        for prm in bloque.parameters():
            prm.requires_grad = True
    cabezas_prm = [p for c in (modelo.cabeza_tamano, modelo.cabeza_grupo, modelo.cabeza_estado) for p in c.parameters()]
    opt = torch.optim.AdamW([
        {"params": [p for p in modelo.backbone.parameters() if p.requires_grad], "lr": 1e-4},
        {"params": cabezas_prm, "lr": 5e-4},
    ], weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epocas_ajuste)
    for e in range(args.epocas_ajuste):
        t0 = time.time()
        print(f"[ajuste {e + 1}] perdida={entrenar_epoch(modelo, cargadores['train'], opt, criterios, dispositivo):.4f} ({time.time() - t0:.0f}s)")
        sched.step()
        evaluar_y_guardar(f"ajuste_{e + 1}")

    modelo.load_state_dict(mejor["estado"])
    print("Mejor epoca:", mejor["epoca"])

    # Calibracion y metricas
    temperatura = {n: 1.0 for n, _, _ in cabezas}
    metricas = {"mejor_epoca": mejor["epoca"]}
    if "val" in cargadores:
        logits, ys = predecir(modelo, cargadores["val"], dispositivo)
        temperatura = {n: ajustar_temperatura(l, y) for (n, _, _), l, y in zip(cabezas, logits, ys)}
        metricas["val"] = {f"f1_macro_{n}": f1_macro(l, y) for (n, _, _), l, y in zip(cabezas, logits, ys)}
    if "val" in cargadores:
        metricas["val_por_clase"] = metricas_por_clase(cabezas, logits, ys)
    if "test" in cargadores:
        logits, ys = predecir(modelo, cargadores["test"], dispositivo)
        metricas["test"] = {f"f1_macro_{n}": f1_macro(l, y) for (n, _, _), l, y in zip(cabezas, logits, ys)}
        # SCRUM-105: por clase (no solo el promedio), matriz de confusion e IC 95 %
        # por bootstrap: con tan pocas imagenes por clase, el intervalo importa.
        metricas["test_por_clase"] = metricas_por_clase(cabezas, logits, ys)
        for (nombre, clases, _), lg, y in zip(cabezas, logits, ys):
            m = y != IGNORAR
            if m.any():
                print(f"\nTEST {nombre}\n", classification_report(
                    y[m].numpy(), lg[m].argmax(1).numpy(), labels=list(range(len(clases))),
                    target_names=clases, zero_division=0))
        guardar_predicciones(args.salida / f"{args.version}_predicciones_test.csv", part["test"],
                             cabezas, logits, temperatura)
    print("Temperaturas:", temperatura, "| Metricas:", json.dumps(metricas, ensure_ascii=False)[:2000])

    # SCRUM-105: Grad-CAM sobre el conjunto de prueba (o validacion si no hay prueba),
    # para revisar si el modelo mira al perro o a la panoleta, el marco o el logo.
    filas_cam = part["test"] or part["val"]
    if args.gradcam and filas_cam:
        metricas["gradcam"] = generar_gradcam(modelo, filas_cam[:args.gradcam], raiz,
                                              args.salida / "gradcam", dispositivo)
        print("Grad-CAM:", metricas["gradcam"])

    # Exportacion
    args.salida.mkdir(parents=True, exist_ok=True)
    ruta_onnx = args.salida / f"{args.version}.onnx"
    modelo.eval().cpu()
    torch.onnx.export(
        modelo, torch.randn(1, 3, LADO, LADO), ruta_onnx,
        input_names=["imagen"], output_names=["tamano", "grupo", "estado"],
        dynamic_axes={"imagen": {0: "lote"}, "tamano": {0: "lote"}, "grupo": {0: "lote"},
                      "estado": {0: "lote"}},
        opset_version=17,
    )
    # Las versiones nuevas de PyTorch guardan los pesos en un archivo aparte
    # (.onnx.data). Se juntan en un solo archivo (~20 MB) para copiar solo el .onnx.
    import onnx

    onnx.save(onnx.load(str(ruta_onnx)), str(ruta_onnx), save_as_external_data=False)
    externo = ruta_onnx.with_name(ruta_onnx.name + ".data")
    if externo.exists():
        externo.unlink()
    meta = {
        "version": args.version,
        "arquitectura": "efficientnet_b0 + cabezas tamano/grupo/estado",
        "clases_tamano": CLASES_TAMANO,
        "clases_grupo": CLASES_GRUPO,
        # Sin etiquetas de estado la cabeza no se entrena: no se publica.
        "clases_estado": CLASES_ESTADO if con_estado else None,
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
