"""
SCRUM-101 — Mapeo de las 120 razas de Stanford Dogs a las clases del tarifario.

PROBLEMA QUE RESUELVE
---------------------
Stanford Dogs no está etiquetado con las variables que el negocio necesita.
Trae una sola etiqueta: la raza. El tarifario de SCRUM-98 no cobra por raza,
cobra por TAMAÑO (peso) y por TIPO DE PELAJE. Sin un puente explícito entre
ambos vocabularios, el dataset de 20 580 imágenes es inutilizable para el
Agente de Cotización por Imagen.

NATURALEZA DE LA ETIQUETA DERIVADA (decisión D2)
------------------------------------------------
La etiqueta que produce este módulo es una ETIQUETA DÉBIL (weak label), no
verdad de campo. La raza induce una distribución de pesos, no un peso. Un
Beagle adulto pesa entre 9 y 11 kg, de modo que atraviesa el corte de 9,0 kg
del tarifario: la raza NO determina la clase de tamaño. Tratar estas etiquetas
como verdad de campo inflaría artificialmente las métricas de SCRUM-105.

Por eso cada raza se declara con su RANGO de peso estándar y el módulo marca
como `ambigua` toda raza cuyo rango cruce un corte del tarifario. Las razas
ambiguas se excluyen del entrenamiento supervisado de tamaño (uso por defecto)
o se admiten con peso muestral reducido si se activa `--incluir-ambiguas`.

FUENTE DE LOS RANGOS
--------------------
Rangos de peso adulto de los estándares de raza (FCI / clubes de raza de
referencia). Son valores de referencia bibliográfica, no mediciones del
negocio: su función es descartar razas ambiguas y estimar cobertura, nunca
sustituir el peso declarado por el cliente, que es el dato que el tarifario
usa en producción.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from clases import (
    CLAVE_FUERA_DE_RANGO,
    CLAVES_PELAJE,
    PELAJE_NO_CUBIERTO,
    clasificar_rango_peso,
)


@dataclass(frozen=True)
class Raza:
    slug: str            # nombre de carpeta en Stanford Dogs, en minúsculas
    nombre_es: str
    peso_min_kg: float
    peso_max_kg: float
    pelaje: str
    observacion: str = ""


# Razas que NO son perros domésticos de compañía. Stanford Dogs las incluye por
# herencia de la jerarquía WordNet de ImageNet. Nunca serán clientes de un salón
# de grooming: se excluyen del dataset (decisión D3).
NO_DOMESTICAS = {"dingo", "dhole", "african_hunting_dog"}


RAZAS: tuple[Raza, ...] = (
    # --- Toy y compañía -----------------------------------------------------
    Raza("chihuahua", "Chihuahua", 1.5, 3.0, "corto"),
    Raza("japanese_spaniel", "Spaniel japonés (Chin)", 1.8, 4.1, "largo"),
    Raza("maltese_dog", "Bichón maltés", 3.0, 4.0, "largo"),
    Raza("pekinese", "Pekinés", 3.2, 6.4, "largo"),
    Raza("shih-tzu", "Shih Tzu", 4.0, 7.3, "largo"),
    Raza("blenheim_spaniel", "Cavalier King Charles (Blenheim)", 5.9, 8.2, "largo"),
    Raza("papillon", "Papillón", 2.3, 4.5, "largo"),
    Raza("toy_terrier", "Terrier inglés toy", 2.7, 3.6, "corto"),
    # --- Sabuesos y lebreles ------------------------------------------------
    Raza("rhodesian_ridgeback", "Rhodesian Ridgeback", 32.0, 39.0, "corto"),
    Raza("afghan_hound", "Lebrel afgano", 23.0, 27.0, "largo"),
    Raza("basset", "Basset Hound", 20.0, 29.0, "corto"),
    Raza("beagle", "Beagle", 9.0, 11.3, "corto"),
    Raza("bloodhound", "Sabueso de San Huberto", 36.0, 50.0, "corto"),
    Raza("bluetick", "Bluetick Coonhound", 20.0, 36.0, "corto"),
    Raza("black-and-tan_coonhound", "Coonhound negro y fuego", 29.0, 34.0, "corto"),
    Raza("walker_hound", "Treeing Walker Coonhound", 20.0, 32.0, "corto"),
    Raza("english_foxhound", "Foxhound inglés", 29.0, 34.0, "corto"),
    Raza("redbone", "Redbone Coonhound", 20.0, 32.0, "corto"),
    Raza("borzoi", "Borzoi", 27.0, 48.0, "largo"),
    Raza("irish_wolfhound", "Lebrel irlandés", 48.0, 70.0, "doble", PELAJE_NO_CUBIERTO),
    Raza("italian_greyhound", "Galgo italiano", 3.0, 5.0, "corto"),
    Raza("whippet", "Whippet", 9.0, 19.0, "corto"),
    Raza("ibizan_hound", "Podenco ibicenco", 20.0, 25.0, "corto"),
    Raza("norwegian_elkhound", "Elkhound noruego", 20.0, 25.0, "doble"),
    Raza("otterhound", "Otterhound", 30.0, 52.0, "doble", PELAJE_NO_CUBIERTO),
    Raza("saluki", "Saluki", 16.0, 29.0, "largo"),
    Raza("scottish_deerhound", "Deerhound escocés", 34.0, 50.0, "doble", PELAJE_NO_CUBIERTO),
    Raza("weimaraner", "Braco de Weimar", 25.0, 40.0, "corto"),
    # --- Terriers -----------------------------------------------------------
    Raza("staffordshire_bullterrier", "Staffordshire Bull Terrier", 11.0, 17.0, "corto"),
    Raza("american_staffordshire_terrier", "American Staffordshire Terrier", 18.0, 32.0, "corto"),
    Raza("bedlington_terrier", "Bedlington Terrier", 8.0, 10.0, "rizado"),
    Raza("border_terrier", "Border Terrier", 5.0, 7.0, "doble", PELAJE_NO_CUBIERTO),
    Raza("kerry_blue_terrier", "Kerry Blue Terrier", 15.0, 18.0, "rizado"),
    Raza("irish_terrier", "Terrier irlandés", 11.0, 12.0, "doble", PELAJE_NO_CUBIERTO),
    Raza("norfolk_terrier", "Norfolk Terrier", 5.0, 5.5, "doble", PELAJE_NO_CUBIERTO),
    Raza("norwich_terrier", "Norwich Terrier", 5.0, 5.5, "doble", PELAJE_NO_CUBIERTO),
    Raza("yorkshire_terrier", "Yorkshire Terrier", 2.0, 3.2, "largo"),
    Raza("wire-haired_fox_terrier", "Fox Terrier de pelo duro", 7.0, 9.0, "doble", PELAJE_NO_CUBIERTO),
    Raza("lakeland_terrier", "Lakeland Terrier", 7.0, 8.0, "doble", PELAJE_NO_CUBIERTO),
    Raza("sealyham_terrier", "Sealyham Terrier", 8.0, 9.5, "doble", PELAJE_NO_CUBIERTO),
    Raza("airedale", "Airedale Terrier", 19.0, 25.0, "doble", PELAJE_NO_CUBIERTO),
    Raza("cairn", "Cairn Terrier", 6.0, 7.5, "doble", PELAJE_NO_CUBIERTO),
    Raza("australian_terrier", "Terrier australiano", 5.0, 7.0, "doble", PELAJE_NO_CUBIERTO),
    Raza("dandie_dinmont", "Dandie Dinmont Terrier", 8.0, 11.0, "doble", PELAJE_NO_CUBIERTO),
    Raza("boston_bull", "Boston Terrier", 4.5, 11.0, "corto"),
    Raza("miniature_schnauzer", "Schnauzer miniatura", 5.4, 9.1, "doble", PELAJE_NO_CUBIERTO),
    Raza("giant_schnauzer", "Schnauzer gigante", 25.0, 48.0, "doble", PELAJE_NO_CUBIERTO),
    Raza("standard_schnauzer", "Schnauzer estándar", 14.0, 20.0, "doble", PELAJE_NO_CUBIERTO),
    Raza("scotch_terrier", "Terrier escocés", 8.5, 10.0, "doble", PELAJE_NO_CUBIERTO),
    Raza("tibetan_terrier", "Terrier tibetano", 8.0, 14.0, "largo"),
    Raza("silky_terrier", "Silky Terrier", 3.5, 4.5, "largo"),
    Raza("soft-coated_wheaten_terrier", "Wheaten Terrier de pelo suave", 13.6, 20.4, "rizado"),
    Raza("west_highland_white_terrier", "West Highland White Terrier", 6.8, 9.1, "doble", PELAJE_NO_CUBIERTO),
    Raza("lhasa", "Lhasa Apso", 5.4, 8.2, "largo"),
    # --- Cobradores, muestra y spaniels -------------------------------------
    Raza("flat-coated_retriever", "Retriever de pelo liso", 25.0, 36.0, "largo"),
    Raza("curly-coated_retriever", "Retriever de pelo rizado", 29.0, 43.0, "rizado"),
    Raza("golden_retriever", "Golden Retriever", 25.0, 34.0, "doble"),
    Raza("labrador_retriever", "Labrador Retriever", 25.0, 36.0, "doble"),
    Raza("chesapeake_bay_retriever", "Retriever de la bahía de Chesapeake", 25.0, 36.0, "doble"),
    Raza("german_short-haired_pointer", "Braco alemán de pelo corto", 20.0, 32.0, "corto"),
    Raza("vizsla", "Vizsla", 20.0, 29.0, "corto"),
    Raza("english_setter", "Setter inglés", 20.0, 36.0, "largo"),
    Raza("irish_setter", "Setter irlandés", 24.0, 32.0, "largo"),
    Raza("gordon_setter", "Setter Gordon", 20.0, 36.0, "largo"),
    Raza("brittany_spaniel", "Epagneul bretón", 13.6, 18.1, "largo"),
    Raza("clumber", "Clumber Spaniel", 25.0, 39.0, "largo"),
    Raza("english_springer", "Springer Spaniel inglés", 18.0, 25.0, "largo"),
    Raza("welsh_springer_spaniel", "Springer Spaniel galés", 16.0, 20.0, "largo"),
    Raza("cocker_spaniel", "Cocker Spaniel", 9.5, 14.5, "largo"),
    Raza("sussex_spaniel", "Sussex Spaniel", 16.0, 20.0, "largo"),
    Raza("irish_water_spaniel", "Spaniel de agua irlandés", 20.0, 30.0, "rizado"),
    # --- Pastores y boyeros -------------------------------------------------
    Raza("kuvasz", "Kuvasz", 32.0, 52.0, "doble"),
    Raza("schipperke", "Schipperke", 3.0, 9.0, "doble"),
    Raza("groenendael", "Pastor belga Groenendael", 20.0, 30.0, "largo"),
    Raza("malinois", "Pastor belga Malinois", 20.0, 30.0, "corto"),
    Raza("briard", "Briard", 25.0, 45.0, "largo"),
    Raza("kelpie", "Kelpie australiano", 14.0, 20.0, "doble"),
    Raza("komondor", "Komondor", 36.0, 61.0, "rizado", "acordonado"),
    Raza("old_english_sheepdog", "Bobtail (Antiguo pastor inglés)", 27.0, 45.0, "largo"),
    Raza("shetland_sheepdog", "Pastor de Shetland", 5.0, 11.0, "largo"),
    Raza("collie", "Collie", 18.0, 30.0, "largo"),
    Raza("border_collie", "Border Collie", 14.0, 20.0, "doble"),
    Raza("bouvier_des_flandres", "Bouvier de Flandes", 27.0, 40.0, "doble", PELAJE_NO_CUBIERTO),
    Raza("rottweiler", "Rottweiler", 35.0, 60.0, "corto"),
    Raza("german_shepherd", "Pastor alemán", 22.0, 40.0, "doble"),
    Raza("doberman", "Dóberman", 27.0, 45.0, "corto"),
    Raza("miniature_pinscher", "Pinscher miniatura", 3.5, 5.0, "corto"),
    Raza("greater_swiss_mountain_dog", "Gran boyero suizo", 39.0, 64.0, "doble"),
    Raza("bernese_mountain_dog", "Boyero de Berna", 32.0, 52.0, "largo"),
    Raza("appenzeller", "Boyero de Appenzell", 22.0, 32.0, "doble"),
    Raza("entlebucher", "Boyero de Entlebuch", 20.0, 30.0, "corto"),
    # --- Molosos y tipo dogo ------------------------------------------------
    Raza("boxer", "Bóxer", 25.0, 32.0, "corto"),
    Raza("bull_mastiff", "Bullmastiff", 45.0, 59.0, "corto"),
    Raza("tibetan_mastiff", "Dogo del Tíbet", 34.0, 73.0, "doble"),
    Raza("french_bulldog", "Bulldog francés", 8.0, 14.0, "corto"),
    Raza("great_dane", "Gran danés", 45.0, 90.0, "corto"),
    Raza("saint_bernard", "San Bernardo", 54.0, 82.0, "doble"),
    # --- Nórdicos y spitz ---------------------------------------------------
    Raza("eskimo_dog", "Perro esquimal", 27.0, 47.0, "doble"),
    Raza("malamute", "Malamute de Alaska", 34.0, 43.0, "doble"),
    Raza("siberian_husky", "Husky siberiano", 16.0, 27.0, "doble"),
    Raza("samoyed", "Samoyedo", 16.0, 30.0, "doble"),
    Raza("pomeranian", "Pomerania", 1.9, 3.5, "doble"),
    Raza("chow", "Chow Chow", 20.0, 32.0, "doble"),
    Raza("keeshond", "Keeshond", 14.0, 20.0, "doble"),
    # --- Varios -------------------------------------------------------------
    Raza("affenpinscher", "Affenpinscher", 3.0, 6.0, "doble", PELAJE_NO_CUBIERTO),
    Raza("basenji", "Basenji", 9.0, 12.0, "corto"),
    Raza("pug", "Pug", 6.3, 8.1, "corto"),
    Raza("leonberg", "Leonberger", 41.0, 75.0, "largo"),
    Raza("newfoundland", "Terranova", 45.0, 68.0, "largo"),
    Raza("great_pyrenees", "Montaña de los Pirineos", 39.0, 73.0, "largo"),
    Raza("brabancon_griffon", "Grifón de Bruselas", 3.5, 6.0, "doble", PELAJE_NO_CUBIERTO),
    Raza("pembroke", "Welsh Corgi Pembroke", 10.0, 14.0, "doble"),
    Raza("cardigan", "Welsh Corgi Cardigan", 11.0, 17.0, "doble"),
    Raza("toy_poodle", "Caniche toy", 2.0, 3.5, "rizado"),
    Raza("miniature_poodle", "Caniche miniatura", 5.0, 8.0, "rizado"),
    Raza("standard_poodle", "Caniche estándar", 20.0, 32.0, "rizado"),
    Raza("mexican_hairless", "Xoloitzcuintle", 4.0, 25.0, "corto", "sin pelo; tres variedades de talla"),
    # --- Cánidos NO domésticos (se excluyen del dataset) --------------------
    Raza("dingo", "Dingo", 13.0, 20.0, "corto", "no doméstico"),
    Raza("dhole", "Dhole (perro salvaje asiático)", 12.0, 20.0, "corto", "no doméstico"),
    Raza("african_hunting_dog", "Licaón", 18.0, 36.0, "corto", "no doméstico"),
)


def construir_mapeo() -> list[dict]:
    """Deriva, para cada raza, la clase de tamaño, la ambigüedad y la decisión de uso."""
    filas: list[dict] = []
    for r in RAZAS:
        clave_tamano, ambigua = clasificar_rango_peso(r.peso_min_kg, r.peso_max_kg)
        no_domestica = r.slug in NO_DOMESTICAS
        fuera = clave_tamano == CLAVE_FUERA_DE_RANGO

        if no_domestica:
            uso, motivo = "excluida", "cánido no doméstico: no es cliente posible del salón"
        elif fuera:
            uso, motivo = "excluida", "supera los 45 kg que cotiza el tarifario v1"
        elif ambigua:
            uso, motivo = "solo_pelaje", "el rango de peso cruza un corte del tarifario"
        else:
            uso, motivo = "completa", ""

        filas.append(
            {
                "slug": r.slug,
                "nombre_es": r.nombre_es,
                "peso_min_kg": r.peso_min_kg,
                "peso_max_kg": r.peso_max_kg,
                "tamano": clave_tamano,
                "tamano_ambiguo": int(ambigua),
                "pelaje": r.pelaje,
                "pelaje_observacion": r.observacion,
                "uso": uso,
                "motivo_exclusion": motivo,
            }
        )
    return filas


def escribir_csv(destino: str | Path) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    filas = construir_mapeo()
    with destino.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    return destino


def validar_cobertura(slugs_encontrados: list[str]) -> dict[str, list[str]]:
    """
    Control de integridad: contrasta las carpetas realmente descargadas de
    Stanford Dogs contra la tabla. Que una raza quede sin mapear es un fallo
    silencioso grave (imágenes sin etiqueta o con etiqueta equivocada), por lo
    que el pipeline se detiene si esta función devuelve faltantes.
    """
    conocidos = {r.slug for r in RAZAS}
    encontrados = {s.lower() for s in slugs_encontrados}
    return {
        "sin_mapeo": sorted(encontrados - conocidos),
        "mapeadas_no_presentes": sorted(conocidos - encontrados),
    }


def integridad_tabla() -> list[str]:
    """Autocomprobaciones de la tabla misma."""
    problemas: list[str] = []
    slugs = [r.slug for r in RAZAS]
    if len(slugs) != len(set(slugs)):
        problemas.append("Hay slugs duplicados en la tabla de razas.")
    if len(RAZAS) != 120:
        problemas.append(f"La tabla tiene {len(RAZAS)} razas; Stanford Dogs define 120.")
    for r in RAZAS:
        if r.pelaje not in CLAVES_PELAJE:
            problemas.append(f"{r.slug}: pelaje '{r.pelaje}' fuera de la taxonomía del tarifario.")
        if r.peso_min_kg > r.peso_max_kg:
            problemas.append(f"{r.slug}: rango de peso invertido.")
        if r.peso_min_kg <= 0:
            problemas.append(f"{r.slug}: peso mínimo no positivo.")
    return problemas


if __name__ == "__main__":
    for p in integridad_tabla():
        print("AVISO:", p)
    ruta = escribir_csv(Path(__file__).resolve().parents[1] / "config" / "mapeo_razas.csv")
    print(f"Mapeo escrito en {ruta} ({len(RAZAS)} razas).")
