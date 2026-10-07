"""
SCRUM-101 — Mapeo de las 120 razas de Stanford Dogs a las clases del tarifario v2.

PROBLEMA QUE RESUELVE
---------------------
Stanford Dogs no está etiquetado con las variables que el negocio necesita.
Trae una sola etiqueta: la raza. El tarifario v2 de SCRUM-98 no cobra por raza:
cobra por TAMAÑO, por GRUPO DE MANTO (la técnica de grooming) y por ESTADO del
pelo. Este módulo es el puente entre ambos vocabularios para las dos variables
que sí se pueden derivar de la raza (tamaño y grupo). El estado del pelo no se
deriva de la raza: solo sale de fotografías propias etiquetadas una por una.

NATURALEZA DE LA ETIQUETA DERIVADA (decisión D2)
------------------------------------------------
Las etiquetas que produce este módulo son ETIQUETAS DÉBILES (weak labels), no
verdad de campo:

  - Tamaño: la raza induce una distribución de pesos, no un peso. Un Beagle
    adulto pesa entre 9 y 11 kg y atraviesa el corte de 9,0 kg del tarifario.
    Toda raza cuyo rango cruce un corte se marca `tamano_ambiguo` y no aporta
    etiqueta de tamaño (uso `solo_grupo`).
  - Grupo de manto: la raza define la técnica de grooming en la gran mayoría
    de los casos, pero hay variedades (el chihuahua de pelo largo, por ejemplo)
    que se anotan en `grupo_observacion`.

ORIGEN DEL GRUPO (`grupo_origen`)
---------------------------------
  - `tarifario_v2`: la raza figura en `app/cotizacion/tarifario_v2.json` y el
    grupo se toma de ahí. Las pruebas verifican que ambos coincidan, así un
    cambio en el tarifario obliga a actualizar esta tabla.
  - `equipo`: asignación del equipo por analogía con las razas del tarifario
    (por ejemplo, terriers de pelo duro -> A como el schnauzer). Es un SUPUESTO
    pendiente de validar con la propietaria.

FUENTE DE LOS RANGOS DE PESO
----------------------------
Rangos de peso adulto de los estándares de raza (FCI / clubes de raza de
referencia). Son valores bibliográficos, no mediciones del negocio.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from clases import (
    CLAVE_FUERA_DE_RANGO,
    CLAVES_GRUPO,
    RUTA_TARIFARIO_V2,
    clasificar_rango_peso,
)

A_maquina, B_deslanado, C_cepillado, D_corto = CLAVES_GRUPO


@dataclass(frozen=True)
class Raza:
    slug: str            # nombre de carpeta en Stanford Dogs, en minúsculas
    nombre_es: str
    peso_min_kg: float
    peso_max_kg: float
    grupo: str
    observacion: str = ""


# Razas que NO son perros domésticos de compañía. Stanford Dogs las incluye por
# herencia de la jerarquía WordNet de ImageNet. Nunca serán clientes de un salón
# de grooming: se excluyen del dataset (decisión D3).
NO_DOMESTICAS = {"dingo", "dhole", "african_hunting_dog"}


# Razas de Stanford Dogs que también figuran en el tarifario v2 (slug -> clave
# de `razas` en el tarifario). Para estas el grupo NO lo decide el equipo: se
# copia del tarifario y una prueba verifica que sigan coincidiendo.
EN_TARIFARIO: dict[str, str] = {
    "shih-tzu": "shih tzu",
    "yorkshire_terrier": "yorkie",
    "toy_poodle": "caniche pequeno",
    "miniature_poodle": "caniche pequeno",
    "standard_poodle": "poodle",
    "miniature_schnauzer": "schnauzer",
    "standard_schnauzer": "schnauzer",
    "giant_schnauzer": "schnauzer",
    "pekinese": "pequines",
    "chihuahua": "chihuahua",
    "pug": "pug",
    "siberian_husky": "husky",
    "golden_retriever": "golden",
    "old_english_sheepdog": "pastor ingles",
    "maltese_dog": "maltes",
    "lhasa": "lhasa apso",
    "cocker_spaniel": "cocker",
    "pomeranian": "pomerania",
    "labrador_retriever": "labrador",
    "german_shepherd": "pastor aleman",
    "samoyed": "samoyedo",
    "border_collie": "border collie",
    "beagle": "beagle",
    "french_bulldog": "bulldog frances",
    "american_staffordshire_terrier": "pitbull",
    "rottweiler": "rottweiler",
}


RAZAS: tuple[Raza, ...] = (
    # --- Toy y compañía -----------------------------------------------------
    Raza("chihuahua", "Chihuahua", 1.5, 3.0, D_corto, "existe variedad de pelo largo (iría a C)"),
    Raza("japanese_spaniel", "Spaniel japonés (Chin)", 1.8, 4.1, C_cepillado),
    Raza("maltese_dog", "Bichón maltés", 3.0, 4.0, A_maquina),
    Raza("pekinese", "Pekinés", 3.2, 6.4, A_maquina),
    Raza("shih-tzu", "Shih Tzu", 4.0, 7.3, A_maquina),
    Raza("blenheim_spaniel", "Cavalier King Charles (Blenheim)", 5.9, 8.2, C_cepillado),
    Raza("papillon", "Papillón", 2.3, 4.5, C_cepillado),
    Raza("toy_terrier", "Terrier inglés toy", 2.7, 3.6, D_corto),
    # --- Sabuesos y lebreles ------------------------------------------------
    Raza("rhodesian_ridgeback", "Rhodesian Ridgeback", 32.0, 39.0, D_corto),
    Raza("afghan_hound", "Lebrel afgano", 23.0, 27.0, C_cepillado),
    Raza("basset", "Basset Hound", 20.0, 29.0, D_corto),
    Raza("beagle", "Beagle", 9.0, 11.3, D_corto),
    Raza("bloodhound", "Sabueso de San Huberto", 36.0, 50.0, D_corto),
    Raza("bluetick", "Bluetick Coonhound", 20.0, 36.0, D_corto),
    Raza("black-and-tan_coonhound", "Coonhound negro y fuego", 29.0, 34.0, D_corto),
    Raza("walker_hound", "Treeing Walker Coonhound", 20.0, 32.0, D_corto),
    Raza("english_foxhound", "Foxhound inglés", 29.0, 34.0, D_corto),
    Raza("redbone", "Redbone Coonhound", 20.0, 32.0, D_corto),
    Raza("borzoi", "Borzoi", 27.0, 48.0, C_cepillado),
    Raza("irish_wolfhound", "Lebrel irlandés", 48.0, 70.0, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("italian_greyhound", "Galgo italiano", 3.0, 5.0, D_corto),
    Raza("whippet", "Whippet", 9.0, 19.0, D_corto),
    Raza("ibizan_hound", "Podenco ibicenco", 20.0, 25.0, D_corto),
    Raza("norwegian_elkhound", "Elkhound noruego", 20.0, 25.0, B_deslanado),
    Raza("otterhound", "Otterhound", 30.0, 52.0, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("saluki", "Saluki", 16.0, 29.0, C_cepillado),
    Raza("scottish_deerhound", "Deerhound escocés", 34.0, 50.0, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("weimaraner", "Braco de Weimar", 25.0, 40.0, D_corto),
    # --- Terriers -----------------------------------------------------------
    Raza("staffordshire_bullterrier", "Staffordshire Bull Terrier", 11.0, 17.0, D_corto, "en Quito se lo llama pitbull"),
    Raza("american_staffordshire_terrier", "American Staffordshire Terrier", 18.0, 32.0, D_corto, "en Quito se lo llama pitbull"),
    Raza("bedlington_terrier", "Bedlington Terrier", 8.0, 10.0, A_maquina),
    Raza("border_terrier", "Border Terrier", 5.0, 7.0, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("kerry_blue_terrier", "Kerry Blue Terrier", 15.0, 18.0, A_maquina),
    Raza("irish_terrier", "Terrier irlandés", 11.0, 12.0, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("norfolk_terrier", "Norfolk Terrier", 5.0, 5.5, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("norwich_terrier", "Norwich Terrier", 5.0, 5.5, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("yorkshire_terrier", "Yorkshire Terrier", 2.0, 3.2, A_maquina),
    Raza("wire-haired_fox_terrier", "Fox Terrier de pelo duro", 7.0, 9.0, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("lakeland_terrier", "Lakeland Terrier", 7.0, 8.0, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("sealyham_terrier", "Sealyham Terrier", 8.0, 9.5, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("airedale", "Airedale Terrier", 19.0, 25.0, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("cairn", "Cairn Terrier", 6.0, 7.5, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("australian_terrier", "Terrier australiano", 5.0, 7.0, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("dandie_dinmont", "Dandie Dinmont Terrier", 8.0, 11.0, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("boston_bull", "Boston Terrier", 4.5, 11.0, D_corto),
    Raza("miniature_schnauzer", "Schnauzer miniatura", 5.4, 9.1, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("giant_schnauzer", "Schnauzer gigante", 25.0, 48.0, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("standard_schnauzer", "Schnauzer estándar", 14.0, 20.0, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("scotch_terrier", "Terrier escocés", 8.5, 10.0, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("tibetan_terrier", "Terrier tibetano", 8.0, 14.0, A_maquina),
    Raza("silky_terrier", "Silky Terrier", 3.5, 4.5, A_maquina),
    Raza("soft-coated_wheaten_terrier", "Wheaten Terrier de pelo suave", 13.6, 20.4, A_maquina),
    Raza("west_highland_white_terrier", "West Highland White Terrier", 6.8, 9.1, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("lhasa", "Lhasa Apso", 5.4, 8.2, A_maquina),
    # --- Cobradores, muestra y spaniels -------------------------------------
    Raza("flat-coated_retriever", "Retriever de pelo liso", 25.0, 36.0, C_cepillado),
    Raza("curly-coated_retriever", "Retriever de pelo rizado", 29.0, 43.0, D_corto, "rizo corto y apretado: no se pasa máquina"),
    Raza("golden_retriever", "Golden Retriever", 25.0, 34.0, C_cepillado),
    Raza("labrador_retriever", "Labrador Retriever", 25.0, 36.0, B_deslanado),
    Raza("chesapeake_bay_retriever", "Retriever de la bahía de Chesapeake", 25.0, 36.0, B_deslanado),
    Raza("german_short-haired_pointer", "Braco alemán de pelo corto", 20.0, 32.0, D_corto),
    Raza("vizsla", "Vizsla", 20.0, 29.0, D_corto),
    Raza("english_setter", "Setter inglés", 20.0, 36.0, C_cepillado),
    Raza("irish_setter", "Setter irlandés", 24.0, 32.0, C_cepillado),
    Raza("gordon_setter", "Setter Gordon", 20.0, 36.0, C_cepillado),
    Raza("brittany_spaniel", "Epagneul bretón", 13.6, 18.1, C_cepillado),
    Raza("clumber", "Clumber Spaniel", 25.0, 39.0, C_cepillado),
    Raza("english_springer", "Springer Spaniel inglés", 18.0, 25.0, C_cepillado),
    Raza("welsh_springer_spaniel", "Springer Spaniel galés", 16.0, 20.0, C_cepillado),
    Raza("cocker_spaniel", "Cocker Spaniel", 9.5, 14.5, A_maquina),
    Raza("sussex_spaniel", "Sussex Spaniel", 16.0, 20.0, C_cepillado),
    Raza("irish_water_spaniel", "Spaniel de agua irlandés", 20.0, 30.0, A_maquina),
    # --- Pastores y boyeros -------------------------------------------------
    Raza("kuvasz", "Kuvasz", 32.0, 52.0, B_deslanado),
    Raza("schipperke", "Schipperke", 3.0, 9.0, B_deslanado),
    Raza("groenendael", "Pastor belga Groenendael", 20.0, 30.0, B_deslanado),
    Raza("malinois", "Pastor belga Malinois", 20.0, 30.0, B_deslanado),
    Raza("briard", "Briard", 25.0, 45.0, C_cepillado),
    Raza("kelpie", "Kelpie australiano", 14.0, 20.0, B_deslanado),
    Raza("komondor", "Komondor", 36.0, 61.0, C_cepillado, "acordonado"),
    Raza("old_english_sheepdog", "Bobtail (Antiguo pastor inglés)", 27.0, 45.0, A_maquina),
    Raza("shetland_sheepdog", "Pastor de Shetland", 5.0, 11.0, C_cepillado),
    Raza("collie", "Collie", 18.0, 30.0, C_cepillado),
    Raza("border_collie", "Border Collie", 14.0, 20.0, C_cepillado),
    Raza("bouvier_des_flandres", "Bouvier de Flandes", 27.0, 40.0, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("rottweiler", "Rottweiler", 35.0, 60.0, D_corto),
    Raza("german_shepherd", "Pastor alemán", 22.0, 40.0, B_deslanado),
    Raza("doberman", "Dóberman", 27.0, 45.0, D_corto),
    Raza("miniature_pinscher", "Pinscher miniatura", 3.5, 5.0, D_corto),
    Raza("greater_swiss_mountain_dog", "Gran boyero suizo", 39.0, 64.0, B_deslanado),
    Raza("bernese_mountain_dog", "Boyero de Berna", 32.0, 52.0, C_cepillado),
    Raza("appenzeller", "Boyero de Appenzell", 22.0, 32.0, B_deslanado),
    Raza("entlebucher", "Boyero de Entlebuch", 20.0, 30.0, B_deslanado),
    # --- Molosos y tipo dogo ------------------------------------------------
    Raza("boxer", "Bóxer", 25.0, 32.0, D_corto),
    Raza("bull_mastiff", "Bullmastiff", 45.0, 59.0, D_corto),
    Raza("tibetan_mastiff", "Dogo del Tíbet", 34.0, 73.0, B_deslanado),
    Raza("french_bulldog", "Bulldog francés", 8.0, 14.0, D_corto),
    Raza("great_dane", "Gran danés", 45.0, 90.0, D_corto),
    Raza("saint_bernard", "San Bernardo", 54.0, 82.0, B_deslanado),
    # --- Nórdicos y spitz ---------------------------------------------------
    Raza("eskimo_dog", "Perro esquimal", 27.0, 47.0, B_deslanado),
    Raza("malamute", "Malamute de Alaska", 34.0, 43.0, B_deslanado),
    Raza("siberian_husky", "Husky siberiano", 16.0, 27.0, B_deslanado),
    Raza("samoyed", "Samoyedo", 16.0, 30.0, B_deslanado),
    Raza("pomeranian", "Pomerania", 1.9, 3.5, B_deslanado),
    Raza("chow", "Chow Chow", 20.0, 32.0, B_deslanado),
    Raza("keeshond", "Keeshond", 14.0, 20.0, B_deslanado),
    # --- Varios -------------------------------------------------------------
    Raza("affenpinscher", "Affenpinscher", 3.0, 6.0, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("basenji", "Basenji", 9.0, 12.0, D_corto),
    Raza("pug", "Pug", 6.3, 8.1, B_deslanado),
    Raza("leonberg", "Leonberger", 41.0, 75.0, B_deslanado),
    Raza("newfoundland", "Terranova", 45.0, 68.0, B_deslanado),
    Raza("great_pyrenees", "Montaña de los Pirineos", 39.0, 73.0, B_deslanado),
    Raza("brabancon_griffon", "Grifón de Bruselas", 3.5, 6.0, A_maquina, "pelo duro: se asume máquina, como el schnauzer"),
    Raza("pembroke", "Welsh Corgi Pembroke", 10.0, 14.0, B_deslanado),
    Raza("cardigan", "Welsh Corgi Cardigan", 11.0, 17.0, B_deslanado),
    Raza("toy_poodle", "Caniche toy", 2.0, 3.5, A_maquina),
    Raza("miniature_poodle", "Caniche miniatura", 5.0, 8.0, A_maquina),
    Raza("standard_poodle", "Caniche estándar", 20.0, 32.0, A_maquina),
    Raza("mexican_hairless", "Xoloitzcuintle", 4.0, 25.0, D_corto, "sin pelo; tres variedades de talla"),
    # --- Cánidos NO domésticos (se excluyen del dataset) --------------------
    Raza("dingo", "Dingo", 13.0, 20.0, D_corto, "no doméstico"),
    Raza("dhole", "Dhole (perro salvaje asiático)", 12.0, 20.0, D_corto, "no doméstico"),
    Raza("african_hunting_dog", "Licaón", 18.0, 36.0, D_corto, "no doméstico"),
)


def construir_mapeo() -> list[dict]:
    """Deriva, para cada raza, la clase de tamaño, el grupo de manto y la decisión de uso."""
    filas: list[dict] = []
    for r in RAZAS:
        clave_tamano, ambigua = clasificar_rango_peso(r.peso_min_kg, r.peso_max_kg)
        no_domestica = r.slug in NO_DOMESTICAS
        fuera = clave_tamano == CLAVE_FUERA_DE_RANGO

        if no_domestica:
            uso, motivo = "excluida", "cánido no doméstico: no es cliente posible del salón"
        elif fuera:
            uso, motivo = "excluida", "supera los 45 kg que cotiza el tarifario"
        elif ambigua:
            uso, motivo = "solo_grupo", "el rango de peso cruza un corte del tarifario"
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
                "grupo": r.grupo,
                "grupo_origen": "tarifario_v2" if r.slug in EN_TARIFARIO else "equipo",
                "raza_tarifario": EN_TARIFARIO.get(r.slug, ""),
                "grupo_observacion": r.observacion,
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
        if r.grupo not in CLAVES_GRUPO:
            problemas.append(f"{r.slug}: grupo '{r.grupo}' fuera de la taxonomía del tarifario v2.")
        if r.peso_min_kg > r.peso_max_kg:
            problemas.append(f"{r.slug}: rango de peso invertido.")
        if r.peso_min_kg <= 0:
            problemas.append(f"{r.slug}: peso mínimo no positivo.")
    desconocidos = set(EN_TARIFARIO) - set(slugs)
    if desconocidos:
        problemas.append(f"EN_TARIFARIO menciona razas que no están en la tabla: {sorted(desconocidos)}")
    return problemas


def verificar_grupos_contra_tarifario(ruta_tarifario: str | Path = RUTA_TARIFARIO_V2) -> list[str]:
    """
    Para las razas que también están en el tarifario v2, el grupo de esta tabla
    debe ser el mismo que el del tarifario. Si alguien cambia el tarifario (por
    ejemplo, cuando la propietaria valide los supuestos), esta verificación
    obliga a actualizar el mapeo antes de volver a generar el dataset.
    """
    ruta = Path(ruta_tarifario)
    if not ruta.exists():
        return [f"No se encontró el tarifario en {ruta}. Verificación no ejecutada."]
    razas_t = json.loads(ruta.read_text(encoding="utf-8")).get("razas", {})
    problemas = []
    por_slug = {r.slug: r for r in RAZAS}
    for slug, clave in EN_TARIFARIO.items():
        entrada = razas_t.get(clave)
        if not isinstance(entrada, dict):
            problemas.append(f"{slug}: la raza '{clave}' ya no está en el tarifario.")
            continue
        if entrada.get("grupo") and entrada["grupo"] != por_slug[slug].grupo:
            problemas.append(f"{slug}: grupo {por_slug[slug].grupo} en el mapeo, "
                             f"{entrada['grupo']} en el tarifario ('{clave}').")
    return problemas


if __name__ == "__main__":
    for p in integridad_tabla() + verificar_grupos_contra_tarifario():
        print("AVISO:", p)
    ruta = escribir_csv(Path(__file__).resolve().parents[1] / "config" / "mapeo_razas.csv")
    print(f"Mapeo escrito en {ruta} ({len(RAZAS)} razas).")
