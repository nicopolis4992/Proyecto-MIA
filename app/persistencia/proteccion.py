"""
Protección de los datos personales guardados en la base del piloto (LOPDP arts. 10 y 37).

Mismo enfoque que el esquema de Supabase de SCRUM-74 (db/mia_agenda/seguridad.py),
aplicado al SQLite del prototipo:

* Seudónimo (HMAC-SHA256, determinista): para BUSCAR por teléfono (sesiones,
  citas previas de un cliente, mensajes en espera) sin guardar el número.
* Cifrado (Fernet = AES-128-CBC + HMAC-SHA256, admite rotación de claves): para
  RECUPERAR el número, el nombre y los textos, porque el sistema debe responder
  por WhatsApp. Solo la aplicación tiene las claves; el archivo de la base solo
  contiene datos cifrados.

Claves en variables de entorno, nunca en el repositorio:
    MIA_CLAVES_CIFRADO              una o más claves Fernet separadas por comas
                                    (la primera es la vigente; las demás, para rotar)
    MIA_CLAVE_SEUDONIMO_OPERACION   texto de al menos 32 caracteres

Sin claves, la protección queda desactivada (desarrollo y pruebas) y el panel
lo marca como error en modo producción. Los valores cifrados llevan el prefijo
"enc:" y los seudónimos "h:", así una base existente se migra sin perder datos.

Generar una clave Fernet:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os

logger = logging.getLogger("proteccion")

PREFIJO_CIFRADO = "enc:"
PREFIJO_SEUDONIMO = "h:"


class Proteccion:
    def __init__(self, claves_cifrado: list[str] | None = None, clave_seudonimo: str | None = None):
        self._fernet = None
        self._clave_hmac = None
        if claves_cifrado and clave_seudonimo:
            if len(clave_seudonimo) < 32:
                raise ValueError("MIA_CLAVE_SEUDONIMO_OPERACION debe tener al menos 32 caracteres")
            from cryptography.fernet import Fernet, MultiFernet

            self._fernet = MultiFernet([Fernet(c.strip().encode("ascii")) for c in claves_cifrado if c.strip()])
            self._clave_hmac = clave_seudonimo.encode("utf-8")

    @classmethod
    def desde_entorno(cls) -> "Proteccion":
        claves = [c for c in os.getenv("MIA_CLAVES_CIFRADO", "").split(",") if c.strip()]
        seudonimo = os.getenv("MIA_CLAVE_SEUDONIMO_OPERACION", "")
        p = cls(claves, seudonimo)
        if not p.activa:
            logger.warning("Proteccion de datos DESACTIVADA: faltan MIA_CLAVES_CIFRADO o MIA_CLAVE_SEUDONIMO_OPERACION")
        return p

    @property
    def activa(self) -> bool:
        return self._fernet is not None

    def seudonimo(self, valor: str) -> str:
        """Clave de búsqueda determinista. Sin protección, el valor tal cual."""
        if not self.activa or valor.startswith(PREFIJO_SEUDONIMO):
            return valor
        return PREFIJO_SEUDONIMO + hmac.new(self._clave_hmac, ("tel|" + valor).encode("utf-8"),
                                            hashlib.sha256).hexdigest()

    def cifrar(self, texto: str | None) -> str | None:
        if texto is None or not self.activa or str(texto).startswith(PREFIJO_CIFRADO):
            return texto
        return PREFIJO_CIFRADO + self._fernet.encrypt(str(texto).encode("utf-8")).decode("ascii")

    def descifrar(self, valor: str | None) -> str | None:
        """Lo que no lleva el prefijo (datos anteriores a la protección) se devuelve tal cual."""
        if not isinstance(valor, str) or not valor.startswith(PREFIJO_CIFRADO):
            return valor
        if not self.activa:
            raise RuntimeError("Hay datos cifrados en la base pero faltan las claves (MIA_CLAVES_CIFRADO)")
        return self._fernet.decrypt(valor[len(PREFIJO_CIFRADO):].encode("ascii")).decode("utf-8")
