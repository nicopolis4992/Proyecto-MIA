"""
SCRUM-105 — Estándar de oro a distancia: la propietaria clasifica las fotos de
PRUEBA en un Google Form desde su celular, sin ver propuestas de ningún modelo.

1) Generar el script de Google Apps Script (no gasta nada):
    python -m entrenamiento.clasificador_imagen.formulario_ciego script
   -> READ/formulario_ciego.gs. Pegarlo en script.google.com y ejecutar
      `crearFormulario`. El registro muestra el enlace para la propietaria.

2) Cuando responda: en el formulario, Respuestas -> Ver en Hojas de cálculo ->
   Archivo -> Descargar -> CSV, y:
    python -m entrenamiento.clasificador_imagen.formulario_ciego importar --respuestas <csv>
   -> READ/estandar_oro_propietaria.csv, el mismo formato del modo ciego de
      revisar.py, listo para comparar_cnn_gemini --estandar-oro.

Las fotos se identifican como "Foto 1..48": el formulario no muestra el nombre
del archivo (dice "antes"/"despues", una pista del estado) ni la mascota.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from entrenamiento.clasificador_imagen.revisar import COLUMNAS_CIEGO, RAIZ, preparar_ciego

READ = RAIZ / "READ"
CARPETA_DRIVE = "Grupo7_VisionArtificial_S1/Proyecto_MIA/dataset/imagenes"

# Texto que ve la propietaria -> etiqueta del tarifario. "" = no se puede saber.
OPCIONES = {
    "tamano": {
        "Pequeño (hasta 9 kg)": "pequeno",
        "Mediano (de 9 a 18 kg)": "mediano",
        "Grande (más de 18 kg)": "grande",
        "No se puede saber con esta foto": "",
    },
    "grupo": {
        "Máquina: el pelo le crece y se corta (shih tzu, poodle, schnauzer)": "A_maquina",
        "Doble capa: pelo tupido con subpelo, bota mucho (husky, pug, labrador)": "B_deslanado",
        "Cepillado: pelo largo y liso que no se pasa a máquina (golden, border collie)": "C_cepillado",
        "Corto: pelo corto pegado al cuerpo (chihuahua, pitbull)": "D_corto",
        "No se puede saber con esta foto": "",
    },
    "estado": {
        "Sin nudos": "sin_motas",
        "Algunos nudos": "moderado",
        "Muy enredado o apelmazado": "severo",
        "No se ve en esta foto": "",
    },
}
PREGUNTA = {"tamano": "Tamaño", "grupo": "Tipo de pelo", "estado": "Estado del pelo"}

PLANTILLA_GS = r"""/**
 * Lina's Pet Salón · Clasificación de fotos (estándar de oro, SCRUM-105)
 * Generado por entrenamiento/clasificador_imagen/formulario_ciego.py: no editar a mano.
 *
 * Uso: script.google.com -> Nuevo proyecto -> pegar todo -> Guardar ->
 * elegir la función crearFormulario -> Ejecutar -> autorizar el acceso a Drive y Forms.
 * Al terminar, "Registro de ejecución" muestra el enlace para la propietaria.
 */
const RUTA_CARPETA = "__CARPETA__";   // carpeta de Drive con las fotos
const ID_CARPETA = "";                // opcional: el ID de la carpeta, si se movió
const FOTOS = __FOTOS__;              // [id, archivo] en el orden del formulario
const OPCIONES = __OPCIONES__;
const PREGUNTA = __PREGUNTA__;

function crearFormulario() {
  const carpeta = ID_CARPETA ? DriveApp.getFolderById(ID_CARPETA) : buscarCarpeta(RUTA_CARPETA);
  const form = FormApp.create("Lina's Pet Salón · Clasificación de fotos");
  form.setDescription(
    "Gracias por ayudarnos 🐾 Son " + FOTOS.length + " fotos de perritos del salón. En cada una, marque " +
    "el tamaño, el tipo de pelo y el estado del pelo como lo haría al cotizar. Responda con lo primero que " +
    "piense; si con la foto no se puede saber, elija esa opción. Toma unos 15 minutos y puede hacerlo desde el celular.");
  form.setProgressBar(true);
  form.setCollectEmail(false);
  form.setConfirmationMessage("¡Listo, muchas gracias! 🙌");

  FOTOS.forEach(function (foto, i) {
    const n = i + 1;
    if (i > 0) form.addPageBreakItem().setTitle("Foto " + n + " de " + FOTOS.length);
    const archivos = carpeta.getFilesByName(foto[1]);
    if (!archivos.hasNext()) throw new Error("No encontré la foto " + foto[1] + " en " + RUTA_CARPETA);
    // El nombre del archivo dice antes/despues: se reemplaza por uno neutro.
    const imagen = archivos.next().getBlob().setName(foto[0] + ".jpg");
    form.addImageItem().setTitle("Foto " + n).setImage(imagen).setWidth(600);
    ["tamano", "grupo", "estado"].forEach(function (campo) {
      form.addMultipleChoiceItem()
        .setTitle("Foto " + n + " · " + PREGUNTA[campo])
        .setChoiceValues(Object.keys(OPCIONES[campo]))
        .setRequired(true);
    });
  });
  Logger.log("ENLACE PARA LA PROPIETARIA: " + form.getPublishedUrl());
  Logger.log("Editar y ver respuestas (solo el equipo): " + form.getEditUrl());
}

function buscarCarpeta(ruta) {
  let carpeta = DriveApp.getRootFolder();
  ruta.split("/").forEach(function (nombre) {
    const sub = carpeta.getFoldersByName(nombre);
    if (!sub.hasNext()) throw new Error("No encontré la carpeta '" + nombre + "' (ruta: " + ruta + ")");
    carpeta = sub.next();
  });
  return carpeta;
}
"""


def _orden(manifiesto: Path) -> list[dict]:
    """Mismo orden aleatorio (semilla 42) que el modo ciego de revisar.py."""
    ruta = READ / "estandar_oro_propietaria.csv"
    preparar_ciego(manifiesto, ruta)
    return list(csv.DictReader(open(ruta, encoding="utf-8-sig")))


def generar_script(manifiesto: Path, carpeta: str, salida: Path) -> int:
    filas = _orden(manifiesto)
    fotos = [[f["id_imagen"], Path(f["ruta"]).name] for f in filas]
    codigo = (PLANTILLA_GS.replace("__CARPETA__", carpeta)
              .replace("__FOTOS__", json.dumps(fotos))
              .replace("__OPCIONES__", json.dumps(OPCIONES, ensure_ascii=False, indent=2))
              .replace("__PREGUNTA__", json.dumps(PREGUNTA, ensure_ascii=False)))
    salida.write_text(codigo, encoding="utf-8")
    return len(fotos)


def importar(respuestas: Path, manifiesto: Path) -> tuple[int, int]:
    """Pasa la ultima respuesta del formulario al CSV del estandar de oro."""
    filas = _orden(manifiesto)
    lector = list(csv.DictReader(open(respuestas, encoding="utf-8-sig")))
    if not lector:
        raise SystemExit("El CSV de respuestas está vacío.")
    resp = lector[-1]  # si respondio mas de una vez, vale la ultima
    por_titulo = {k.strip(): v.strip() for k, v in resp.items() if k}
    completas = 0
    for i, f in enumerate(filas, 1):
        valores = {}
        for campo, titulo in PREGUNTA.items():
            texto = por_titulo.get(f"Foto {i} · {titulo}")
            if texto is None:
                raise SystemExit(f"Falta la columna 'Foto {i} · {titulo}' en {respuestas.name}")
            if texto not in OPCIONES[campo]:
                raise SystemExit(f"Respuesta no reconocida en Foto {i} · {titulo}: {texto!r}")
            valores[campo] = OPCIONES[campo][texto]
        sirve = bool(valores["tamano"] or valores["grupo"])
        f.update(valores, revisado="si", es_perro="si" if sirve else "no")
        completas += 1
    with open(READ / "estandar_oro_propietaria.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS_CIEGO)
        w.writeheader()
        w.writerows(filas)
    return completas, len(filas)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("script")
    s.add_argument("--carpeta-drive", default=CARPETA_DRIVE)
    s.add_argument("--salida", type=Path, default=READ / "formulario_ciego.gs")
    i = sub.add_parser("importar")
    i.add_argument("--respuestas", type=Path, required=True)
    for p in (s, i):
        p.add_argument("--manifiesto", type=Path, default=READ / "manifiesto_v2.csv")
    args = ap.parse_args()
    if args.cmd == "script":
        n = generar_script(args.manifiesto, args.carpeta_drive, args.salida)
        print(f"Script con {n} fotos en {args.salida}. Pegarlo en script.google.com y ejecutar crearFormulario.")
    else:
        ok, n = importar(args.respuestas, args.manifiesto)
        print(f"{ok}/{n} fotos importadas en READ/estandar_oro_propietaria.csv")


if __name__ == "__main__":
    main()
