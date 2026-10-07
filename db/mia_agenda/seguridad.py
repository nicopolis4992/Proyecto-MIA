"""Seudonimización y cifrado de los datos de contacto (LOPDP arts. 10 y 37).

Dos mecanismos distintos porque resuelven problemas distintos:

* ``Seudonimizador`` (HMAC-SHA256): produce un identificador DETERMINISTA para
  encontrar al mismo cliente en cada conversación sin guardar su número. No es
  reversible: sirve para buscar, no para contactar.
* ``Cifrador`` (Fernet = AES-128-CBC + HMAC-SHA256, con rotación de claves):
  guarda el número y el nombre de forma RECUPERABLE, porque el sistema debe
  poder responder por WhatsApp. Solo la aplicación tiene la clave; la base de
  datos únicamente ve bytes cifrados.

Separación de claves (decisión D5 del anexo): la clave de seudónimos de la
OPERACIÓN es distinta de la sal de INVESTIGACIÓN usada en SCRUM-63/SCRUM-101.
Si fueran la misma, la base operativa permitiría re-identificar el corpus de
investigación, y destruir la sal al cierre del proyecto dejaría inservible la
búsqueda de clientes en producción.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import unicodedata

from cryptography.fernet import Fernet, MultiFernet

_E164_EC = re.compile(r"^\+593(9\d{8}|[2-7]\d{7})$")   # móvil (9 dígitos) o fijo (8)
_E164_GENERAL = re.compile(r"^\+[1-9]\d{7,14}$")


class ErrorConfiguracion(RuntimeError):
    """Faltan claves o están mal configuradas: el sistema no debe arrancar."""


def normalizar_telefono(telefono: str) -> str:
    """Lleva un número a formato E.164.

    Es la condición para que el seudónimo funcione: «0991234567»,
    «+593 99 123 4567» y «593991234567» son la MISMA persona y deben producir el
    mismo identificador; si no, un cliente aparece duplicado y pierde su
    historial de fidelidad o de referidos.
    """
    if telefono is None:
        raise ValueError("Teléfono vacío")
    crudo = telefono.strip()
    digitos = re.sub(r"\D", "", crudo)
    if not digitos:
        raise ValueError(f"Teléfono sin dígitos: {telefono!r}")

    if crudo.startswith("+") or crudo.startswith("00"):
        numero = "+" + (digitos[2:] if crudo.startswith("00") else digitos)
    elif digitos.startswith("593"):
        numero = "+" + digitos
    elif digitos.startswith("0") and len(digitos) in (9, 10):     # 02xxxxxxx / 09xxxxxxxx
        numero = "+593" + digitos[1:]
    elif len(digitos) == 9 and digitos.startswith("9"):           # 9xxxxxxxx sin el 0
        numero = "+593" + digitos
    else:
        raise ValueError(f"No se reconoce el formato del teléfono: {telefono!r}")

    if numero.startswith("+593"):
        if not _E164_EC.match(numero):
            raise ValueError(f"Número ecuatoriano inválido: {telefono!r}")
    elif not _E164_GENERAL.match(numero):
        raise ValueError(f"Número internacional inválido: {telefono!r}")
    return numero


def normalizar_nombre(nombre: str) -> str:
    """«María  José » y «maria jose» cuentan como el mismo nombre."""
    sin_tildes = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.lower().split())


class Seudonimizador:
    """HMAC-SHA256 con separación de dominio («tel|», «tercero|»)."""

    def __init__(self, clave: bytes):
        if not clave or len(clave) < 32:
            raise ErrorConfiguracion("La clave de seudónimos debe tener al menos 32 bytes")
        self._clave = clave

    def _hmac(self, mensaje: str) -> str:
        return hmac.new(self._clave, mensaje.encode("utf-8"), hashlib.sha256).hexdigest()

    def de_telefono(self, telefono: str) -> str:
        return self._hmac("tel|" + normalizar_telefono(telefono))

    def de_tercero(self, telefono_referente: str, nombre: str) -> str:
        """Tercero sin teléfono: identificado por quién lo refiere + su nombre."""
        return self._hmac("tercero|" + normalizar_telefono(telefono_referente) + "|" + normalizar_nombre(nombre))


class Cifrador:
    """Cifrado autenticado y recuperable. Admite varias claves para rotarlas:
    cifra con la primera y descifra con cualquiera."""

    def __init__(self, claves: list[bytes]):
        if not claves:
            raise ErrorConfiguracion("Se requiere al menos una clave de cifrado")
        self._f = MultiFernet([Fernet(c) for c in claves])

    def cifrar(self, texto: str) -> bytes:
        return self._f.encrypt(texto.encode("utf-8"))

    def descifrar(self, dato: bytes) -> str:
        return self._f.decrypt(bytes(dato)).decode("utf-8")


def desde_entorno() -> tuple[Seudonimizador, Cifrador]:
    """Lee las claves del entorno; nunca del repositorio.

    MIA_CLAVE_SEUDONIMO_OPERACION : texto de ≥ 32 caracteres
    MIA_CLAVES_CIFRADO            : una o más claves Fernet separadas por comas
                                    (la primera es la vigente)
    MIA_SAL_SEUDONIMO             : sal de INVESTIGACIÓN (SCRUM-63/101); solo se
                                    lee para verificar que no se reutiliza aquí.
    """
    clave_seud = os.environ.get("MIA_CLAVE_SEUDONIMO_OPERACION")
    claves_cif = os.environ.get("MIA_CLAVES_CIFRADO")
    if not clave_seud or not claves_cif:
        raise ErrorConfiguracion(
            "Defina MIA_CLAVE_SEUDONIMO_OPERACION y MIA_CLAVES_CIFRADO; sin ellas el registro se detiene."
        )
    sal_investigacion = os.environ.get("MIA_SAL_SEUDONIMO")
    if sal_investigacion and hmac.compare_digest(sal_investigacion, clave_seud):
        raise ErrorConfiguracion(
            "La clave de operación no puede ser la sal de investigación de SCRUM-63/101 (decisión D5)."
        )
    return (
        Seudonimizador(clave_seud.encode("utf-8")),
        Cifrador([c.strip().encode("ascii") for c in claves_cif.split(",") if c.strip()]),
    )
