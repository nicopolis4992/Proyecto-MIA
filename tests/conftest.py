import os
import sys
from pathlib import Path
from types import SimpleNamespace

# Las pruebas nunca tocan la base local ni las APIs reales.
os.environ["MIA_DB_PATH"] = ":memory:"
# Las pruebas existentes simulan clientes cualquiera; el filtro del modo
# pruebas se prueba aparte en test_webhook.py.
os.environ["MIA_MODO"] = "produccion"
os.environ.setdefault("WHATSAPP_ESPERA_BASE_S", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ClienteFalso:
    """Imita genai.Client: devuelve en orden los textos de `respuestas`."""

    def __init__(self, *respuestas: str):
        self.respuestas = list(respuestas)
        self.llamadas = []
        self.models = SimpleNamespace(generate_content=self._generar)

    def _generar(self, **kwargs):
        self.llamadas.append(kwargs)
        return SimpleNamespace(text=self.respuestas.pop(0))
