"""
Diagnóstico de configuración para el despliegue (panel → "Estado del sistema").

Nunca devuelve valores secretos: solo si cada variable está presente y
algunas comprobaciones baratas (formato de números, base escribible, índice
RAG, modelo de imagen). Útil al configurar Railway y Meta por primera vez.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from app import config


def _numero_valido(n: str) -> bool:
    return bool(re.fullmatch(r"593\d{9}", n))


def diagnostico(repo) -> list[dict]:
    revisiones: list[dict] = []

    def agregar(nombre: str, ok: bool, detalle: str, critico: bool = True):
        revisiones.append({"nombre": nombre, "ok": ok, "detalle": detalle,
                           "nivel": "ok" if ok else ("error" if critico else "aviso")})

    agregar("Gemini (GEMINI_API_KEY)", bool(os.getenv("GEMINI_API_KEY")),
            "presente" if os.getenv("GEMINI_API_KEY") else "falta: el bot no puede responder")
    token, phone_id = os.getenv("WHATSAPP_ACCESS_TOKEN", ""), os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    agregar("WhatsApp (token y phone number id)", bool(token and phone_id),
            "presentes" if token and phone_id else "faltan: no se pueden enviar mensajes")
    agregar("Token de verificación del webhook", bool(os.getenv("WHATSAPP_VERIFY_TOKEN")),
            "presente" if os.getenv("WHATSAPP_VERIFY_TOKEN") else "falta: Meta no podrá verificar el webhook")

    prop = config.PROPIETARIA_WHATSAPP
    agregar("Número de la propietaria", _numero_valido(prop),
            f"{prop[:6]}… ok" if _numero_valido(prop) else
            "falta o formato inválido (usar 593 + 9 dígitos, sin + ni 0 inicial)")

    agregar("Modo", True, f"{config.MODO}" + (" (solo números del equipo)" if config.MODO == "pruebas" else
                                              " (atiende a cualquier número)"))
    if config.MODO == "pruebas":
        malos = [n for n in config.NUMEROS_PERMITIDOS if not _numero_valido(n)]
        agregar("Números permitidos", bool(config.NUMEROS_PERMITIDOS) and not malos,
                f"{len(config.NUMEROS_PERMITIDOS)} número(s)" + (f"; formato inválido: {malos}" if malos else "")
                if config.NUMEROS_PERMITIDOS else "ninguno: en modo pruebas el bot no responderá a nadie")

    plantillas = [n for n, v in (("propietaria", config.PLANTILLA_PROPIETARIA),
                                 ("cliente", config.PLANTILLA_CLIENTE)) if v]
    agregar("Plantillas de Meta (regla de 24 h)", len(plantillas) == 2,
            "configuradas" if len(plantillas) == 2 else
            f"faltan ({', '.join({'propietaria', 'cliente'} - set(plantillas))}): si alguien no escribió en "
            "24 h, el bot no puede avisarle (ver docs/plantillas_meta.md)", critico=config.MODO == "produccion")

    cifrado = getattr(getattr(repo, "proteccion", None), "activa", False)
    agregar("Cifrado de datos personales en la base", cifrado,
            "activo: teléfonos, nombres, sesiones y mensajes cifrados" if cifrado else
            "desactivado: faltan MIA_CLAVES_CIFRADO y MIA_CLAVE_SEUDONIMO_OPERACION",
            critico=config.MODO == "produccion")

    pausado = repo.bot_pausado()
    agregar("Bot", not pausado, "PAUSADO por la propietaria: los mensajes se le reenvían a ella "
            "(\"activar bot\" para reanudar)" if pausado else "atendiendo", critico=False)

    from app.notificaciones import correo
    agregar("Correo de respaldo para la propietaria", correo.configurado(),
            "configurado" if correo.configurado() else
            "sin configurar (CORREO_USUARIO, CORREO_CLAVE, CORREO_PROPIETARIA): si WhatsApp falla, "
            "la propietaria no recibe la solicitud", critico=False)

    ruta_db = Path(config.RUTA_DB)
    persistente = str(ruta_db).startswith("/data") or os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "") in str(ruta_db)
    agregar("Base de datos", True, f"{ruta_db}", critico=False)
    if os.getenv("RAILWAY_ENVIRONMENT"):
        agregar("Base de datos en volumen persistente", persistente,
                "sí" if persistente else "NO: las citas se pierden en cada despliegue (montar volumen en /data y "
                                         "MIA_DB_PATH=/data/mia.sqlite3)", critico=False)

    indice = config.RAIZ_APP / "rag" / "indice_local.json"
    agregar("Índice RAG", indice.exists(), "presente" if indice.exists() else "falta: correr python -m app.rag.indexador")

    from app.vision.clasificador import RUTA_ONNX
    agregar("Clasificador de imagen", True,
            "CNN (ONNX)" if RUTA_ONNX.exists() else "Gemini (provisional, la CNN aún no está entrenada)", critico=False)

    cal = bool(os.getenv("GOOGLE_CALENDAR_ID") and (os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
                                                     or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")))
    agregar("Google Calendar", cal, "configurado" if cal else "no configurado (las citas solo quedan en el panel)",
            critico=False)

    from app.limites import CONTADOR_GEMINI

    firma = bool(os.getenv("WHATSAPP_APP_SECRET"))
    agregar("Firma de Meta en el webhook", firma,
            "se verifica (WHATSAPP_APP_SECRET)" if firma else
            "sin verificar: falta WHATSAPP_APP_SECRET (cualquiera con la URL podría enviar mensajes falsos)",
            critico=False)
    limite = int(os.getenv("MIA_LIMITE_GEMINI_DIA", "1500"))
    usadas = CONTADOR_GEMINI.llamadas if CONTADOR_GEMINI.dia == config.ahora().date() else 0
    agregar("Uso de Gemini hoy", usadas < limite * 0.8,
            f"{usadas} de {limite} llamadas (al llegar al tope se pausa el bot); "
            f"máximo {os.getenv('MIA_LIMITE_MENSAJES_HORA', '30')} mensajes por número y hora", critico=False)

    no_entregados = len(repo.mensajes_no_entregados())
    agregar("Mensajes no entregados", no_entregados == 0,
            "ninguno" if not no_entregados else f"{no_entregados}: revisar en el panel", critico=False)
    return revisiones
