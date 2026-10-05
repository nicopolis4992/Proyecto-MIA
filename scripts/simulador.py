"""
Simulador local del prototipo completo, sin WhatsApp real.

Corre el mismo orquestador que produccion (NLU, RAG, cotizacion por foto,
agenda, aprobacion de la propietaria) con Gemini real, pero los mensajes
salientes se imprimen en consola en vez de enviarse por Meta. Sirve para la
demo del 4-oct mientras la cuenta de Meta no este verificada.

Uso:
    python -m scripts.simulador                 # modo interactivo
    python -m scripts.simulador --guion         # conversacion de demostracion
    python -m scripts.simulador --guion --foto ruta/a/perro.jpg

(desde la raiz del proyecto; para una demo visual, usar el panel web /panel)

Comandos en modo interactivo:
    <texto>                 mensaje del cliente actual
    /foto <ruta> [texto]    el cliente envia una foto
    /p <texto>              la propietaria responde (citando la ultima cita enviada)
    /cliente <numero>       cambiar de cliente
    /citas                  ver citas y su estado
    /salir
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

PROPIETARIA = "593900000001"
CLIENTE = "593900000099"


def _preparar():
    from app.agents import orchestrator_graph as og
    from app.mensajeria import MensajeroMemoria
    from app.persistencia.repositorio import Repositorio

    ruta_db = Path(tempfile.gettempdir()) / "mia_simulador.sqlite3"
    ruta_db.unlink(missing_ok=True)
    repo = Repositorio(ruta_db)
    mensajero = MensajeroMemoria(eco=True)
    og.configurar(og.crear_dependencias(repo=repo, mensajero=mensajero, propietaria=PROPIETARIA))
    return og, repo, mensajero


def _ultimo_id_a(mensajero, destino: str) -> str | None:
    ids = [i for d, _, i in mensajero.enviados if d == destino]
    return ids[-1] if ids else None


def _mostrar(quien: str, texto: str | None) -> None:
    if texto:
        print(f"  <<< [bot -> {quien}]\n  {texto.replace(chr(10), chr(10) + '  ')}\n")


def _citas(repo) -> None:
    from app.agenda.mensajes import fecha_legible, texto_total

    for estado in ("pendiente_aprobacion", "aprobada", "rechazada", "confirmada"):
        for c in repo.citas_por_estado(estado):
            print(f"  #{c['id']} [{c['estado']}] {fecha_legible(c['fecha_hora'])} "
                  f"total={texto_total(c)} cliente={c['cliente_telefono']}")


def turno(og, mensajero, remitente: str, texto: str = "", foto: Path | None = None) -> None:
    etiqueta = "propietaria" if remitente == PROPIETARIA else f"cliente {remitente}"
    print(f"--- [{etiqueta}] {'(foto ' + foto.name + ') ' if foto else ''}{texto}")
    id_citado = _ultimo_id_a(mensajero, PROPIETARIA) if remitente == PROPIETARIA else None
    imagen = foto.read_bytes() if foto else None
    _mostrar(etiqueta, og.procesar_mensaje(remitente, texto, imagen, id_citado))


def guion(og, repo, mensajero, foto: Path | None) -> None:
    pasos = [
        (CLIENTE, "Hola, buenas tardes!", None),
        (CLIENTE, "Cuanto cuesta el baño completo para un perro grande?", None),
        (CLIENTE, "Quiero agendar un baño completo con corte para mi perrita Luna, es mestiza", None),
    ]
    pasos.append((CLIENTE, "", foto) if foto else (CLIENTE, "Es mediana, pesa como 12 kilos", None))
    pasos += [
        (CLIENTE, "Su pelo le crece y hay que cortárselo", None),
        (CLIENTE, "Tiene algunos nudos pero es tranquila", None),
        (CLIENTE, "Que la recojan en mi casa por favor, vivo en el Condado", None),
        (CLIENTE, "El jueves a las 5 de la tarde", None),
        (CLIENTE, "1", None),
        (PROPIETARIA, "a las 12 estaría mejor", None),
        (PROPIETARIA, "listo", None),
    ]
    for remitente, texto, f in pasos:
        turno(og, mensajero, remitente, texto, f)
    print("=== Estado final de citas")
    _citas(repo)


def interactivo(og, repo, mensajero) -> None:
    cliente = CLIENTE
    print(__doc__)
    while True:
        try:
            linea = input(f"[{cliente}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not linea:
            continue
        if linea == "/salir":
            break
        if linea == "/citas":
            _citas(repo)
        elif linea.startswith("/cliente "):
            cliente = linea.split(maxsplit=1)[1]
        elif linea.startswith("/p "):
            turno(og, mensajero, PROPIETARIA, linea[3:])
        elif linea.startswith("/foto "):
            partes = linea.split(maxsplit=2)
            turno(og, mensajero, cliente, partes[2] if len(partes) > 2 else "", Path(partes[1]))
        else:
            turno(og, mensajero, cliente, linea)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--guion", action="store_true")
    ap.add_argument("--foto", type=Path)
    args = ap.parse_args()
    og, repo, mensajero = _preparar()
    if args.guion:
        guion(og, repo, mensajero, args.foto)
    else:
        interactivo(og, repo, mensajero)
