"""
Protecciones contra uso abusivo (incidente de Railway, 22-oct-2026).

1. Firma de Meta: cada webhook trae X-Hub-Signature-256 = HMAC-SHA256 del
   cuerpo con el App Secret de la app. Si WHATSAPP_APP_SECRET esta definido,
   se rechaza todo lo que no venga firmado por Meta (mensajes falsos al
   webhook que gastarian Gemini). Sin la variable, no se verifica.
2. Mensajes por numero: mas de MIA_LIMITE_MENSAJES_HORA (30) de un mismo
   numero en una hora no se procesan; se le avisa una sola vez.
3. Tope diario de llamadas a Gemini (MIA_LIMITE_GEMINI_DIA, 1500): al
   alcanzarlo se pausa el bot (los mensajes van a la propietaria) y se avisa.
   Es la red de seguridad del lado de la aplicacion; el corte definitivo es la
   cuota del proyecto en Google Cloud.

Los contadores viven en memoria: se reinician si el servidor se reinicia, lo
que basta para cortar un abuso en curso.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
from collections import deque
from datetime import datetime, timedelta

logger = logging.getLogger("limites")

AVISO_LIMITE = "Recibimos muchos mensajes seguidos 🙏 En un momento le respondemos."


class LimiteGeminiAlcanzado(RuntimeError):
    """Se llego al tope diario de llamadas a Gemini."""


# -- 1. Firma de Meta -------------------------------------------------------------------------------

def firma_valida(cuerpo: bytes, cabecera: str | None, secreto: str | None = None) -> bool:
    secreto = os.getenv("WHATSAPP_APP_SECRET", "") if secreto is None else secreto
    if not secreto:
        return True  # sin App Secret configurado no se verifica (modo compatible)
    if not cabecera or not cabecera.startswith("sha256="):
        return False
    esperado = hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecera.split("=", 1)[1])


# -- 2. Mensajes por numero --------------------------------------------------------------------------

class LimitadorPorNumero:
    def __init__(self, limite: int | None = None, ventana: timedelta = timedelta(hours=1)):
        self.limite = limite or int(os.getenv("MIA_LIMITE_MENSAJES_HORA", "30"))
        self.ventana = ventana
        self._marcas: dict[str, deque] = {}
        self._avisados: set[str] = set()
        self._lock = threading.Lock()

    def permitir(self, numero: str, ahora: datetime) -> str:
        """"ok" (se procesa), "aviso" (se pasa del limite: avisar una vez) o "silencio" (ignorar)."""
        with self._lock:
            marcas = self._marcas.setdefault(numero, deque())
            while marcas and ahora - marcas[0] > self.ventana:
                marcas.popleft()
            if len(marcas) < self.limite:
                marcas.append(ahora)
                self._avisados.discard(numero)
                return "ok"
            if numero in self._avisados:
                return "silencio"
            self._avisados.add(numero)
            logger.warning("Limite de %d mensajes por hora superado por %s", self.limite, numero)
            return "aviso"


# -- 3. Tope diario de Gemini ------------------------------------------------------------------------

class _ContadorDiario:
    def __init__(self):
        self.dia, self.llamadas = None, 0
        self._lock = threading.Lock()

    def sumar(self, limite: int, hoy) -> int:
        with self._lock:
            if hoy != self.dia:
                self.dia, self.llamadas = hoy, 0
            if self.llamadas >= limite:
                raise LimiteGeminiAlcanzado(f"Tope diario de {limite} llamadas a Gemini")
            self.llamadas += 1
            return self.llamadas


CONTADOR_GEMINI = _ContadorDiario()


class ClienteLimitado:
    """Envuelve el cliente de Gemini y cuenta las llamadas del dia."""

    def __init__(self, cliente, limite: int | None = None, contador: _ContadorDiario = CONTADOR_GEMINI):
        self._cliente = cliente
        self.limite = limite or int(os.getenv("MIA_LIMITE_GEMINI_DIA", "1500"))
        self.contador = contador
        self.models = self

    def _contar(self):
        from app.config import ahora
        self.contador.sumar(self.limite, ahora().date())

    def generate_content(self, **kwargs):
        self._contar()
        return self._cliente.models.generate_content(**kwargs)

    def embed_content(self, **kwargs):
        self._contar()
        return self._cliente.models.embed_content(**kwargs)

    def __getattr__(self, nombre):
        return getattr(self._cliente, nombre)
