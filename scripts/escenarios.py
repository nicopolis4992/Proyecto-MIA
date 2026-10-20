"""
Escenarios de conversación completos (clienta + propietaria) con Gemini real.

Son las pruebas manuales que encontraron fallas (30-sep a 06-oct), convertidas
en escenarios repetibles. Se GRABAN una vez (gasta créditos) y después se
REPRODUCEN gratis desde tests/grabaciones/ (también en pytest).

    python -m scripts.escenarios                 # corre todos (graba lo que falte)
    python -m scripts.escenarios reprogramacion  # uno solo
    python -m scripts.escenarios --solo-lectura  # sin llamar a Gemini (falla si falta algo)

Para volver a grabar desde cero (p. ej. tras cambiar prompts): borrar
tests/grabaciones/ y correr de nuevo. El reloj se fija en AHORA para que la
fecha dentro de los prompts no cambie de un día a otro.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
GRABACIONES = RAIZ / "tests" / "grabaciones"
AHORA = "2026-10-06T09:00"  # martes

ESCENARIOS: dict[str, list[tuple[str, str]]] = {
    # Flujo completo con mestiza, restricción vehicular y aprobación con precio.
    # Desde el 19-oct: foto primero (aquí no la envía: se pregunta el tamaño), datos
    # del perro, vacunas, horario; el precio se le dice al cliente al aprobar y
    # la cita se confirma con su "sí".
    "mestiza_puerta_a_puerta": [
        ("cliente", "Quiero agendar un baño completo con corte para mi perrita Luna, es mestiza"),
        ("cliente", "No tengo una foto ahora"),
        ("cliente", "Disculpe, no puedo tomarle foto ahorita"),
        ("cliente", "Es mediana, pesa como 12 kilos"),
        ("cliente", "Su pelo le crece y hay que cortárselo"),
        ("cliente", "Tiene algunos nudos pero es tranquila"),
        ("cliente", "Sí, tiene sus vacunas y está desparasitada"),
        ("cliente", "Que la recojan en mi casa por favor, vivo en el Condado"),
        ("cliente", "El jueves a las 4 de la tarde"),
        ("cliente", "1"),
        ("propietaria", "listo"),
        ("cliente", "sí"),
    ],
    # Capturas del 06-oct: horarios por día, relevo de consulta (algo que la base
    # de conocimiento no sabe), propuesta de la propietaria aceptada por el
    # cliente, "gracias", reprogramación y nueva aprobación.
    "reprogramacion": [
        ("cliente", "Hola, quiero agendar un baño premium para mi perrita Fara, es mediana y de doble capa, "
                    "no tiene nudos y es tranquila"),
        ("cliente", "no tengo foto a la mano"),
        ("cliente", "no puedo enviarla ahora"),
        ("cliente", "si, tiene todas sus vacunas y esta desparasitada"),
        ("cliente", "el lunes esta bien? a que hora tiene disponible?"),
        ("cliente", "y el martes 13 de octubre? que horarios tiene?"),
        ("cliente", "tienen parqueadero?"),
        ("propietaria", "si, hay parqueadero frente al local"),
        ("cliente", "2"),
        ("propietaria", "cambialo a las 2 de la tarde y confirma el precio a USD 22"),
        ("cliente", "si perfecto"),
        ("cliente", "gracias!"),
        ("cliente", "disculpa a esa hora ya no puedo"),
        ("cliente", "1"),
        ("propietaria", "listo"),
        ("cliente", "si"),
    ],
    # Captura del 06-oct: "solo me ofreces hasta las 11".
    "preferencia_tarde": [
        ("cliente", "quiero agendar un baño completo para Toby, es shih tzu, sin nudos y tranquilo, "
                    "lo llevo yo al salon"),
        ("cliente", "no tengo foto"),
        ("cliente", "no puedo ahora"),
        ("cliente", "si, esta vacunado y desparasitado"),
        ("cliente", "que horarios tiene el miercoles?"),
        ("cliente", "no a esa hora no puedo, puedes en la tarde? porque solo me dijiste hasta las 11am"),
        ("cliente", "y despues de las 3?"),
        ("cliente", "la 1"),
    ],
    # Captura del 06-oct y propietaria 18-oct: un Premium sin baño medicado es un
    # Completo; quitar algo no cambia el precio.
    "pedido_especial": [
        ("cliente", "quiero agendar un baño premium para mi perrita Fara, es mediana y de doble capa, "
                    "no tiene nudos y es tranquila"),
        ("cliente", "puedes hacerle este baño pero sin el baño medicado y sin el accesorio?"),
        ("cliente", "no tengo foto, disculpe"),
        ("cliente", "no puedo enviarla ahora"),
        ("cliente", "si, vacunas al dia y desparasitada"),
        ("cliente", "y cuanto me saldria asi?"),
        ("cliente", "la llevo yo al salon el miercoles a la 1 de la tarde"),
    ],
    # Pruebas internas del 16 al 19-oct: disponibilidad antes de terminar los
    # datos, "¿tienen el martes a las 2?" (se responde, no se toma como
    # confirmación), "el martes no puedo, el total seria 22", la clienta que elige
    # otro día y acepta el precio.
    "prueba_propietaria_17oct": [
        ("cliente", "Quiero un baño completo para mi perrita Fara, es mediana de doble capa"),
        ("cliente", "que dias tienen disponibles?"),
        ("cliente", "ahorita no tengo foto"),
        ("cliente", "no puedo enviarla ahora"),
        ("cliente", "no tiene nudos y es tranquila, pero es cieguita"),
        ("cliente", "si, vacunas al dia y desparasitada"),
        ("cliente", "tienen el martes a las 2 de la tarde?"),
        ("cliente", "si"),
        ("propietaria", "el martes no puedo, el total del cobro seria $22"),
        ("cliente", "2"),
        ("propietaria", "listo"),
        ("cliente", "si"),
    ],
}


def correr(nombre: str, solo_lectura: bool = False, mostrar: bool = True):
    """Corre un escenario en una base temporal. Devuelve el objeto Demo final."""
    os.environ["GEMINI_CACHE_DIR"] = str(GRABACIONES / nombre)
    os.environ["MIA_AHORA"] = AHORA
    if solo_lectura:
        os.environ["GEMINI_CACHE_SOLO_LECTURA"] = "1"
    else:
        os.environ.pop("GEMINI_CACHE_SOLO_LECTURA", None)

    sys.path.insert(0, str(RAIZ))
    from app.panel import rutas

    rutas.RUTA_DB_DEMO = Path(tempfile.mkdtemp()) / f"{nombre}.sqlite3"
    demo = rutas.Demo()
    visto = 0
    for canal, texto in ESCENARIOS[nombre]:
        demo.mensaje(canal, texto, None)
        if mostrar:
            for m in demo.chat[visto:]:
                quien = ("CLIENTA" if m["canal"] == "cliente" else "PROPIETARIA") + (" (bot)" if m["autor"] == "bot" else "")
                print(f"[{quien}] {m['texto']}\n")
        visto = len(demo.chat)
    return demo


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    solo_lectura = "--solo-lectura" in sys.argv
    for nombre in args or list(ESCENARIOS):
        print(f"\n{'=' * 70}\nESCENARIO: {nombre}\n{'=' * 70}")
        demo = correr(nombre, solo_lectura)
        for c in demo.repo.todas_las_citas():
            print(f"  cita #{c['id']}: {c['estado']} {c['fecha_hora']} total_acordado={c.get('total_acordado')}")


if __name__ == "__main__":
    main()
