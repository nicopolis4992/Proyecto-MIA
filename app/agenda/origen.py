"""
SCRUM-75: de donde viene el cliente, para el resumen de la propietaria.

- origen: Lina's (por defecto), Lavet (la veterinaria aliada), Hospedaje
  (cliente del servicio de hospedaje) o la red social por la que los
  encontro ("los vi en Instagram").
- referido_por: quien le recomendo el salon ("me recomendo la Sra. Ana").

Se detecta con reglas sobre los mensajes del cliente (sin LLM) y se guarda
en la sesion hasta que se crea la cita. Si el cliente no lo menciona, el
resumen no muestra nada y la propietaria lo sabe por su cuenta.
"""

from __future__ import annotations

import re
import unicodedata

ETIQUETA_ORIGEN = {"linas": "Lina's", "lavet": "Lavet", "hospedaje": "Hospedaje", "instagram": "Instagram",
                   "facebook": "Facebook", "tiktok": "TikTok"}
_RED_SOCIAL = re.compile(r"\b(instagram|insta|facebook|face|tik ?tok)\b")

_LAVET = re.compile(r"\blavet\b")
# "¿tienen hospedaje?" es una pregunta, no el origen: se exige "del/en el hospedaje".
_HOSPEDAJE = re.compile(r"\b(?:del|en el|por el)\s+hospedaje\b")
# Captura hasta 2 palabras (nombre y apellido) despues del verbo, sin articulos ni tratamientos.
_REFERIDO = re.compile(
    r"\b(?:me\s+(?:lo\s+|la\s+|los\s+)?(?:recomendo|recomendaron|refirio|refirieron|paso\s+(?:su|el)\s+(?:numero|contacto))"
    r"|(?:vengo|vine|escribo)\s+de\s+parte\s+de)\s+"
    r"(?:(?:la|el|mi|su)\s+)?(?:(?:sra|sr|senora|senor|dra|dr|vecina|vecino|amiga|amigo|prima|primo|tia|tio)\.?\s+)?"
    r"(?!(?:que|lo|la|los|las|el|este|esta|a|su|sus|para|porque|mucho|muy)\b)"
    r"([a-z]+(?:\s+(?!que\b|y\b|para\b|porque\b|el\b|la\b)[a-z]+)?)")


def _limpio(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def detectar(texto: str) -> dict:
    """{"origen": ..., "referido_por": ...} con lo que se encuentre en el texto."""
    t = _limpio(texto)
    datos: dict = {}
    if _LAVET.search(t):
        datos["origen"] = "lavet"
    elif _HOSPEDAJE.search(t):
        datos["origen"] = "hospedaje"
    elif _RED_SOCIAL.search(t):
        red = _RED_SOCIAL.search(t).group(1).replace(" ", "")
        datos["origen"] = {"insta": "instagram", "face": "facebook"}.get(red, red)
    m = _REFERIDO.search(t)
    if m and m.group(1) not in ETIQUETA_ORIGEN:
        datos["referido_por"] = m.group(1).title()
    return datos


def anotar(repo, telefono: str, texto: str) -> None:
    """Guarda en la sesion del cliente lo que se detecte (no pisa con vacio)."""
    datos = detectar(texto or "")
    if not datos:
        return
    sesion = repo.obtener_sesion(telefono)
    sesion.setdefault("cliente", {}).update(datos)
    repo.guardar_sesion(telefono, sesion)
