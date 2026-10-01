# -*- coding: utf-8 -*-
"""
Proyecto MIA — Lina's Pet Salon
SCRUM-63: Protocolo de anonimizacion del historial de WhatsApp Business.

CRITERIO DE ACEPTACION CUBIERTO
-------------------------------
"dataset anonimizado"

MARCO NORMATIVO
---------------
Ley Organica de Proteccion de Datos Personales del Ecuador (LOPDP, Registro
Oficial Suplemento 459 del 26 de mayo de 2021) y su Reglamento General. La ley
distingue dos tratamientos que no son equivalentes:

  - Seudonimizacion: el dato deja de atribuirse a un titular sin informacion
    adicional, PERO esa informacion adicional existe. El dato seudonimizado
    sigue siendo dato personal y sigue bajo el ambito de la ley.
  - Anonimizacion / disociacion: la reversion es imposible. El resultado deja
    de ser dato personal.

Este modulo implementa SEUDONIMIZACION DETERMINISTA CON SAL SECRETA. Esa
eleccion es deliberada: se necesita que el mismo cliente reciba siempre el mismo
pseudonimo para poder reconstruir hilos de conversacion y evitar fuga de
informacion entre las particiones de entrenamiento y prueba. La anonimizacion
plena se alcanza en el paso final del protocolo: la destruccion de la sal.

PROTOCOLO OPERATIVO (5 pasos)
-----------------------------
1. La propietaria exporta el chat desde WhatsApp Business con la opcion
   "sin archivos multimedia".
2. El export crudo se almacena en `datos_crudos/`, carpeta EXCLUIDA del
   repositorio mediante .gitignore. Nunca se versiona.
3. Se ejecuta este modulo. La sal se lee de la variable de entorno MIA_SALT y
   jamas se escribe en disco dentro del repositorio.
4. Se realiza una revision manual del 100% del corpus seudonimizado por parte
   de un integrante del equipo, buscando identificadores que los patrones
   automaticos no capturaron (apodos, referencias a lugares de trabajo,
   parentescos). Esta revision es obligatoria: la deteccion por expresiones
   regulares tiene recall alto pero no perfecto.
5. Al cierre del proyecto se destruye la sal y se elimina `datos_crudos/`.
   Desde ese momento el corpus publicado es anonimo de forma irreversible y
   puede anexarse al informe de titulacion.

Uso:
    export MIA_SALT="<cadena secreta generada una sola vez>"
    python anonimizador.py --entrada datos_crudos/chat.txt --salida corpus_anonimizado.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Patrones de identificadores directos
# ---------------------------------------------------------------------------

# Telefono ecuatoriano: movil 09XXXXXXXX, fijo 0X XXX XXXX, formato internacional +593
PATRON_TELEFONO = re.compile(
    r"(?:\+?593[\s\-]?)?(?:0?9\d{8}|0?[2-7]\d{7})\b"
)

# Cedula ecuatoriana: 10 digitos. Se exige limite de palabra para no capturar montos.
PATRON_CEDULA = re.compile(r"\b\d{10}\b")

# RUC: 13 digitos terminados en 001
PATRON_RUC = re.compile(r"\b\d{10}001\b")

PATRON_EMAIL = re.compile(r"\b[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+\b")

PATRON_URL = re.compile(r"https?://\S+|www\.\S+")

# Numero de cuenta bancaria: secuencias largas de digitos
PATRON_CUENTA = re.compile(r"\b\d{8,20}\b")

# Encabezado de linea del export de WhatsApp:
# "12/3/25, 14:32 - Nombre Apellido: mensaje"  (Android)
# "[12/3/25 14:32:05] Nombre Apellido: mensaje" (iOS)
PATRON_LINEA_ANDROID = re.compile(
    r"^(?P<fecha>\d{1,2}/\d{1,2}/\d{2,4}),?\s+(?P<hora>\d{1,2}:\d{2}(?::\d{2})?\s*(?:[ap]\.?\s?m\.?)?)\s*-\s*(?P<autor>[^:]{1,60}):\s(?P<texto>.*)$",
    re.IGNORECASE,
)
PATRON_LINEA_IOS = re.compile(
    r"^\[(?P<fecha>\d{1,2}/\d{1,2}/\d{2,4}),?\s+(?P<hora>\d{1,2}:\d{2}(?::\d{2})?\s*(?:[ap]\.?\s?m\.?)?)\]\s*(?P<autor>[^:]{1,60}):\s(?P<texto>.*)$",
    re.IGNORECASE,
)

# Direcciones: calle/av. seguida de texto, o referencia a conjunto/edificio
PATRON_DIRECCION = re.compile(
    r"\b(?:calle|av\.?|avenida|pasaje|conjunto|urbanizacion|urbanizaci[oó]n|edificio|edif\.?|manzana|mz\.?)\s+[\wÁÉÍÓÚÑáéíóúñ\.\-]+(?:\s+[\wÁÉÍÓÚÑáéíóúñ\.\-]+){0,4}",
    re.IGNORECASE,
)

# Marcadores de sistema que WhatsApp inserta y que deben descartarse
RUIDO_SISTEMA = (
    "<multimedia omitido>",
    "<media omitted>",
    "se eliminó este mensaje",
    "se elimino este mensaje",
    "los mensajes y las llamadas están cifrados",
    "los mensajes y las llamadas estan cifrados",
    "imagen omitida",
    "audio omitido",
    "video omitido",
    "sticker omitido",
    "gif omitido",
    "documento omitido",
    "null",
)

# Nombres propios frecuentes en Ecuador. Lista de apoyo: complementa, no
# sustituye, la revision manual del paso 4 del protocolo.
NOMBRES_FRECUENTES = {
    "maria", "jose", "juan", "carlos", "luis", "ana", "jorge", "pedro", "andrea",
    "diego", "paola", "cristian", "veronica", "gabriela", "fernando", "patricia",
    "santiago", "daniela", "alejandra", "marco", "esteban", "mateo", "sofia",
    "camila", "valeria", "martin", "nicolas", "sebastian", "josselyn", "jocelyn",
    "michelle", "kevin", "bryan", "jonathan", "evelyn", "wilson", "mayra",
    "jessica", "karina", "lorena", "mauricio", "rodrigo", "ricardo", "javier",
    "alexandra", "monica", "silvia", "cecilia", "rocio", "elizabeth", "doris",
}

# Disparadores de presentacion: "soy X", "me llamo X", "habla X"
PATRON_PRESENTACION = re.compile(
    r"\b(?:soy|me llamo|habla|le habla|mi nombre es)\s+(?P<nombre>[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]{2,15})",
)


def _sal() -> bytes:
    sal = os.environ.get("MIA_SALT")
    if not sal:
        raise SystemExit(
            "ERROR: la variable de entorno MIA_SALT no esta definida.\n"
            "Genere una sal una sola vez y consérvela fuera del repositorio:\n"
            "  export MIA_SALT=\"$(python3 -c 'import secrets;print(secrets.token_hex(32))')\"\n"
            "Al cierre del proyecto, destruyala para completar la anonimizacion."
        )
    return sal.encode("utf-8")


def seudonimo(valor: str, prefijo: str, longitud: int = 6) -> str:
    """Pseudonimo determinista e irreversible sin la sal (HMAC-SHA256 truncado)."""
    normalizado = unicodedata.normalize("NFKD", valor.strip().lower())
    digest = hmac.new(_sal(), normalizado.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{prefijo}_{digest[:longitud].upper()}"


@dataclass
class Estadisticas:
    """Trazabilidad del proceso: cuantas sustituciones de cada tipo se aplicaron."""

    lineas_leidas: int = 0
    lineas_descartadas: int = 0
    mensajes_conservados: int = 0
    sustituciones: dict = field(default_factory=dict)

    def contar(self, tipo: str, n: int = 1) -> None:
        if n:
            self.sustituciones[tipo] = self.sustituciones.get(tipo, 0) + n

    def informe(self) -> str:
        lineas = [
            "Informe de seudonimizacion",
            "-" * 46,
            f"Lineas leidas del export      : {self.lineas_leidas}",
            f"Lineas descartadas (sistema)  : {self.lineas_descartadas}",
            f"Mensajes conservados          : {self.mensajes_conservados}",
            "",
            "Sustituciones aplicadas por tipo:",
        ]
        if not self.sustituciones:
            lineas.append("  (ninguna)")
        for tipo, n in sorted(self.sustituciones.items(), key=lambda kv: -kv[1]):
            lineas.append(f"  {tipo:<22}: {n}")
        lineas += [
            "",
            "RECORDATORIO: la deteccion automatica no sustituye la revision",
            "manual del 100% del corpus (paso 4 del protocolo).",
        ]
        return "\n".join(lineas)


def enmascarar_texto(texto: str, est: Estadisticas) -> str:
    """Sustituye identificadores directos e indirectos dentro de un mensaje."""

    # El orden importa: los patrones mas especificos van primero para que un
    # patron general no consuma una cadena que otro identificaria mejor.
    def _sub(patron: re.Pattern, etiqueta: str, cadena: str) -> str:
        nonlocal est
        encontrados = patron.findall(cadena)
        if encontrados:
            est.contar(etiqueta, len(encontrados))
        return patron.sub(f"[{etiqueta}]", cadena)

    texto = _sub(PATRON_EMAIL, "EMAIL", texto)
    texto = _sub(PATRON_URL, "URL", texto)
    texto = _sub(PATRON_RUC, "RUC", texto)
    texto = _sub(PATRON_TELEFONO, "TELEFONO", texto)
    texto = _sub(PATRON_CEDULA, "CEDULA", texto)
    texto = _sub(PATRON_CUENTA, "CUENTA", texto)
    texto = _sub(PATRON_DIRECCION, "DIRECCION", texto)

    # Nombres anunciados por el propio hablante
    def _reemplazo_presentacion(m: re.Match) -> str:
        est.contar("NOMBRE_PRESENTACION")
        return m.group(0).replace(m.group("nombre"), "[NOMBRE]")

    texto = PATRON_PRESENTACION.sub(_reemplazo_presentacion, texto)

    # Nombres de la lista de apoyo, respetando limites de palabra
    def _reemplazo_lista(m: re.Match) -> str:
        palabra = m.group(0)
        base = unicodedata.normalize("NFKD", palabra.lower())
        base = "".join(c for c in base if not unicodedata.combining(c))
        if base in NOMBRES_FRECUENTES:
            est.contar("NOMBRE_LISTA")
            return "[NOMBRE]"
        return palabra

    texto = re.sub(r"\b[\wÁÉÍÓÚÑáéíóúñ]{3,16}\b", _reemplazo_lista, texto)

    return re.sub(r"\s{2,}", " ", texto).strip()


def es_ruido(texto: str) -> bool:
    bajo = texto.strip().lower()
    if not bajo:
        return True
    return any(marca in bajo for marca in RUIDO_SISTEMA)


def procesar(ruta_entrada: str, ruta_salida: str, id_propietaria: str | None = None) -> Estadisticas:
    """Lee un export de WhatsApp y escribe el CSV seudonimizado."""
    est = Estadisticas()
    filas = []

    with open(ruta_entrada, "r", encoding="utf-8", errors="replace") as fh:
        autor_actual = None
        for linea in fh:
            est.lineas_leidas += 1
            linea = linea.rstrip("\n")

            m = PATRON_LINEA_ANDROID.match(linea) or PATRON_LINEA_IOS.match(linea)
            if m:
                autor_actual = m.group("autor").strip()
                texto = m.group("texto")
                fecha = m.group("fecha")
            elif autor_actual and linea.strip():
                # Continuacion de un mensaje multilinea (nota de voz transcrita,
                # mensaje con saltos de linea).
                texto = linea
                fecha = filas[-1]["fecha"] if filas else ""
            else:
                est.lineas_descartadas += 1
                continue

            if es_ruido(texto):
                est.lineas_descartadas += 1
                continue

            # El rol se determina comparando con el identificador de la propietaria.
            if id_propietaria and autor_actual and id_propietaria.lower() in autor_actual.lower():
                rol = "propietaria"
            else:
                rol = "cliente"

            filas.append(
                {
                    "id_conversacion": seudonimo(autor_actual or "desconocido", "CLI"),
                    "fecha": fecha,
                    "rol": rol,
                    "texto_anonimizado": enmascarar_texto(texto, est),
                    "intencion": "",       # a completar por los anotadores
                    "entidades": "{}",     # a completar por los anotadores
                    "origen": "real",
                }
            )

    # Solo los mensajes del cliente se etiquetan para NLU. Los de la propietaria
    # se conservan porque alimentan la base de conocimiento del agente RAG
    # (SCRUM-99), no el clasificador de intencion.
    est.mensajes_conservados = len(filas)

    with open(ruta_salida, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "id_conversacion", "fecha", "rol",
                "texto_anonimizado", "intencion", "entidades", "origen",
            ],
        )
        writer.writeheader()
        writer.writerows(filas)

    return est


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seudonimiza un export de WhatsApp Business (Proyecto MIA / SCRUM-63)."
    )
    parser.add_argument("--entrada", required=True, help="Ruta del .txt exportado de WhatsApp")
    parser.add_argument("--salida", required=True, help="Ruta del CSV seudonimizado de salida")
    parser.add_argument(
        "--propietaria",
        default=None,
        help="Cadena que identifica a la propietaria en el export, para separar su rol",
    )
    args = parser.parse_args()

    if not os.path.exists(args.entrada):
        print(f"ERROR: no se encontro el archivo {args.entrada}", file=sys.stderr)
        return 1

    est = procesar(args.entrada, args.salida, args.propietaria)
    print(est.informe())
    print(f"\nCorpus seudonimizado escrito en: {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
