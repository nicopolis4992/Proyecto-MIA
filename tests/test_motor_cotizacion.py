# -*- coding: utf-8 -*-
"""
Proyecto MIA — Lina's Pet Salón
SCRUM-98: Pruebas del motor de cotización.

Cada prueba está nombrada según el criterio de aceptación que verifica, para que
la evidencia de cumplimiento sea rastreable desde Jira sin leer el código.

Ejecutar:
    python -m pytest tests/test_motor_cotizacion.py -v
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path

from app.cotizacion.motor_cotizacion import ErrorTarifario, Mascota, Motor, Solicitud

TARIFARIO = Path(__file__).resolve().parents[1] / "app" / "cotizacion" / "tarifario_v1.json"


class BasePrueba(unittest.TestCase):
    def setUp(self):
        self.motor = Motor(TARIFARIO)


class TestCA1RangosPorTamanoYPelaje(BasePrueba):
    """CA1: rangos de precio definidos para tamaño y tipo de pelaje."""

    def test_el_precio_crece_con_el_tamano(self):
        precios = []
        for tam in ("pequeno", "mediano", "grande"):
            c = self.motor.cotizar(
                Solicitud(mascotas=[Mascota(servicio="bano_corte", tamano=tam, pelaje="corto")])
            )
            precios.append(c["subtotal_servicios"])
        self.assertEqual(precios, sorted(precios))
        self.assertLess(precios[0], precios[-1])

    def test_el_precio_crece_con_la_complejidad_del_pelaje(self):
        precios = []
        for pel in ("corto", "largo", "rizado", "doble_capa"):
            c = self.motor.cotizar(
                Solicitud(mascotas=[Mascota(servicio="bano_corte", tamano="mediano", pelaje=pel)])
            )
            precios.append(c["subtotal_servicios"])
        self.assertEqual(precios, sorted(precios))

    def test_las_tres_categorias_de_tamano_estan_definidas(self):
        self.assertEqual(set(self.motor.tamanos), {"pequeno", "mediano", "grande"})

    def test_clasificacion_por_peso_sin_solapamiento(self):
        self.assertEqual(self.motor.tamano_por_peso(5), "pequeno")
        self.assertEqual(self.motor.tamano_por_peso(9), "pequeno")
        self.assertEqual(self.motor.tamano_por_peso(12), "mediano")
        self.assertEqual(self.motor.tamano_por_peso(30), "grande")
        with self.assertRaises(ErrorTarifario):
            self.motor.tamano_por_peso(80)


class TestCA2PuertaAPuertaConfigurable(BasePrueba):
    """CA2: costo adicional configurable para el servicio puerta a puerta."""

    def test_el_domicilio_agrega_un_cargo(self):
        base = self.motor.cotizar(
            Solicitud(mascotas=[Mascota(servicio="bano", tamano="mediano", pelaje="corto")])
        )
        dom = self.motor.cotizar(
            Solicitud(
                mascotas=[Mascota(servicio="bano", tamano="mediano", pelaje="corto")],
                modalidad="puerta_a_puerta", zona="zona_1",
            )
        )
        self.assertGreater(dom["total_estimado"], base["total_estimado"])
        self.assertEqual(dom["subtotal_visita"], 5.0)

    def test_el_cargo_varia_por_zona(self):
        montos = []
        for zona in ("zona_1", "zona_2", "zona_3"):
            c = self.motor.cotizar(
                Solicitud(
                    mascotas=[Mascota(servicio="bano", tamano="mediano", pelaje="corto")],
                    modalidad="puerta_a_puerta", zona=zona,
                )
            )
            montos.append(c["subtotal_visita"])
        self.assertEqual(montos, sorted(montos))

    def test_el_domicilio_se_cobra_una_vez_por_visita_no_por_mascota(self):
        una = self.motor.cotizar(
            Solicitud(
                mascotas=[Mascota(servicio="bano", tamano="pequeno", pelaje="corto")],
                modalidad="puerta_a_puerta", zona="zona_2",
            )
        )
        tres = self.motor.cotizar(
            Solicitud(
                mascotas=[Mascota(servicio="bano", tamano="pequeno", pelaje="corto")] * 3,
                modalidad="puerta_a_puerta", zona="zona_2",
            )
        )
        self.assertEqual(una["subtotal_visita"], tres["subtotal_visita"])

    def test_zona_invalida_falla_de_forma_explicita(self):
        with self.assertRaises(ErrorTarifario):
            self.motor.cotizar(
                Solicitud(
                    mascotas=[Mascota(servicio="bano", tamano="pequeno")],
                    modalidad="puerta_a_puerta", zona="zona_9",
                )
            )


class TestCA3MultiplesMascotas(BasePrueba):
    """CA3: soporta múltiples mascotas en una misma cita con total agregado."""

    def test_el_total_agrega_todas_las_mascotas(self):
        c = self.motor.cotizar(
            Solicitud(
                mascotas=[
                    Mascota(servicio="bano_corte", nombre="A", tamano="pequeno", pelaje="corto"),
                    Mascota(servicio="bano", nombre="B", tamano="grande", pelaje="doble_capa"),
                ]
            )
        )
        self.assertEqual(len(c["detalle_por_mascota"]), 2)
        suma = sum(d["subtotal"] for d in c["detalle_por_mascota"])
        self.assertAlmostEqual(c["subtotal_servicios"], suma, places=2)

    def test_la_segunda_mascota_recibe_descuento(self):
        una = self.motor.cotizar(
            Solicitud(mascotas=[Mascota(servicio="bano_corte", tamano="mediano", pelaje="corto")])
        )
        dos = self.motor.cotizar(
            Solicitud(mascotas=[Mascota(servicio="bano_corte", tamano="mediano", pelaje="corto")] * 2)
        )
        # El total de dos mascotas debe ser menor que el doble de una.
        self.assertLess(dos["subtotal_servicios"], una["subtotal_servicios"] * 2)

    def test_la_duracion_total_es_la_suma_de_las_mascotas(self):
        c = self.motor.cotizar(
            Solicitud(
                mascotas=[
                    Mascota(servicio="bano", tamano="pequeno", pelaje="corto"),
                    Mascota(servicio="bano", tamano="grande", pelaje="corto"),
                ]
            )
        )
        esperado = sum(d["duracion_estimada_min"] for d in c["detalle_por_mascota"])
        self.assertEqual(c["duracion_total_estimada_min"], esperado)

    def test_solicitud_vacia_falla(self):
        with self.assertRaises(ErrorTarifario):
            self.motor.cotizar(Solicitud(mascotas=[]))


class TestCA4ValoresExternosAlCodigo(BasePrueba):
    """CA4: los valores son parametrizables, no están fijos en el código."""

    def test_modificar_el_json_cambia_el_resultado_sin_tocar_codigo(self):
        import copy, tempfile

        original = self.motor.cotizar(
            Solicitud(mascotas=[Mascota(servicio="bano", tamano="mediano", pelaje="corto")])
        )

        datos = copy.deepcopy(self.motor.t)
        for s in datos["servicios"]:
            if s["codigo"] == "bano":
                s["precio_base"]["mediano"] = 99.0

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False)
            ruta = fh.name

        modificado = Motor(ruta).cotizar(
            Solicitud(mascotas=[Mascota(servicio="bano", tamano="mediano", pelaje="corto")])
        )
        self.assertNotEqual(original["total_estimado"], modificado["total_estimado"])
        self.assertEqual(modificado["subtotal_servicios"], 99.0)

    def test_el_tarifario_declara_su_estado_de_validacion(self):
        c = self.motor.cotizar(
            Solicitud(mascotas=[Mascota(servicio="bano", tamano="pequeno", pelaje="corto")])
        )
        # Mientras los precios no estén validados por la propietaria, toda
        # cotización debe arrastrar esa advertencia.
        self.assertEqual(c["estado_validacion_tarifario"], "PENDIENTE_VALIDACION_PROPIETARIA")

    def test_el_iva_es_conmutable_por_configuracion(self):
        import copy, tempfile

        datos = copy.deepcopy(self.motor.t)
        datos["parametros_globales"]["iva"]["aplica"] = True
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False)
            ruta = fh.name

        con_iva = Motor(ruta).cotizar(
            Solicitud(mascotas=[Mascota(servicio="bano", tamano="mediano", pelaje="corto")])
        )
        self.assertGreater(con_iva["iva"], 0)


class TestBandaDeConfianza(BasePrueba):
    """Verifica el mecanismo que sustenta la meta de reducción de variabilidad."""

    def test_mas_datos_declarados_estrecha_la_banda(self):
        sin_datos = self.motor.cotizar(Solicitud(mascotas=[Mascota(servicio="bano_corte")]))
        con_datos = self.motor.cotizar(
            Solicitud(
                mascotas=[Mascota(servicio="bano_corte", tamano="pequeno", pelaje="largo",
                                  estado_manto="sin_nudos", comportamiento_conocido=True)]
            )
        )
        self.assertGreater(
            sin_datos["rango_estimado"]["semiamplitud"],
            con_datos["rango_estimado"]["semiamplitud"],
        )

    def test_cliente_recurrente_reduce_la_incertidumbre(self):
        nuevo = self.motor.cotizar(
            Solicitud(mascotas=[Mascota(servicio="bano", tamano="mediano", pelaje="corto")],
                      cliente_recurrente=False)
        )
        recurrente = self.motor.cotizar(
            Solicitud(mascotas=[Mascota(servicio="bano", tamano="mediano", pelaje="corto")],
                      cliente_recurrente=True)
        )
        self.assertLess(
            recurrente["rango_estimado"]["incertidumbre_relativa"],
            nuevo["rango_estimado"]["incertidumbre_relativa"],
        )

    def test_datos_completos_producen_precio_comprometido(self):
        c = self.motor.cotizar(
            Solicitud(
                mascotas=[Mascota(servicio="bano_corte", tamano="pequeno", pelaje="corto",
                                  estado_manto="sin_nudos", comportamiento_conocido=True)],
                cliente_recurrente=True,
            )
        )
        self.assertEqual(c["tipo_cotizacion"], "precio_comprometido")
        self.assertLessEqual(c["rango_estimado"]["semiamplitud"], 2.5)

    def test_sin_datos_el_sistema_pide_lo_que_falta_en_lugar_de_prometer(self):
        c = self.motor.cotizar(Solicitud(mascotas=[Mascota(servicio="bano_corte")]))
        self.assertEqual(c["tipo_cotizacion"], "rango_estimado")
        self.assertIn("tamano", c["datos_faltantes"])
        self.assertIn("necesito confirmar", c["mensaje_sugerido"])

    def test_los_supuestos_asumidos_quedan_registrados(self):
        c = self.motor.cotizar(Solicitud(mascotas=[Mascota(servicio="bano_corte")]))
        supuestos = c["detalle_por_mascota"][0]["supuestos"]
        self.assertTrue(any("Tamaño no declarado" in s for s in supuestos))


class TestRestriccionVehicular(BasePrueba):
    """Pico y placa: debe bloquear ventanas horarias, no días completos."""

    def test_bloquea_en_ventana_restringida(self):
        c = self.motor.cotizar(
            Solicitud(
                mascotas=[Mascota(servicio="bano", tamano="mediano", pelaje="corto")],
                modalidad="puerta_a_puerta", zona="zona_1",
                fecha_hora=datetime(2026, 9, 17, 7, 30),  # jueves 07:30
            )
        )
        self.assertTrue(c["restriccion_vehicular"]["bloquea"])

    def test_no_bloquea_en_la_ventana_libre_del_mismo_dia(self):
        c = self.motor.cotizar(
            Solicitud(
                mascotas=[Mascota(servicio="bano", tamano="mediano", pelaje="corto")],
                modalidad="puerta_a_puerta", zona="zona_1",
                fecha_hora=datetime(2026, 9, 17, 11, 0),  # jueves 11:00
            )
        )
        self.assertFalse(c["restriccion_vehicular"]["bloquea"])

    def test_no_aplica_el_fin_de_semana(self):
        c = self.motor.cotizar(
            Solicitud(
                mascotas=[Mascota(servicio="bano", tamano="mediano", pelaje="corto")],
                modalidad="puerta_a_puerta", zona="zona_1",
                fecha_hora=datetime(2026, 9, 19, 7, 30),  # sábado
            )
        )
        self.assertFalse(c["restriccion_vehicular"]["aplica"])

    def test_no_aplica_si_el_servicio_es_en_salon(self):
        c = self.motor.cotizar(
            Solicitud(
                mascotas=[Mascota(servicio="bano", tamano="mediano", pelaje="corto")],
                modalidad="salon",
                fecha_hora=datetime(2026, 9, 17, 7, 30),
            )
        )
        self.assertFalse(c["restriccion_vehicular"]["aplica"])


class TestValidaciones(BasePrueba):
    """El motor debe fallar de forma explícita, nunca devolver un precio erróneo."""

    def test_servicio_inexistente(self):
        with self.assertRaises(ErrorTarifario):
            self.motor.cotizar(Solicitud(mascotas=[Mascota(servicio="masaje_relajante")]))

    def test_deslanado_no_aplica_a_pelaje_corto(self):
        with self.assertRaises(ErrorTarifario):
            self.motor.cotizar(
                Solicitud(mascotas=[Mascota(servicio="deslanado", tamano="grande", pelaje="corto")])
            )

    def test_estado_de_manto_invalido(self):
        with self.assertRaises(ErrorTarifario):
            self.motor.cotizar(
                Solicitud(mascotas=[Mascota(servicio="bano", tamano="pequeno",
                                            pelaje="corto", estado_manto="catastrofico")])
            )

    def test_recargo_de_visita_declarado_como_de_mascota(self):
        with self.assertRaises(ErrorTarifario):
            self.motor.cotizar(
                Solicitud(mascotas=[Mascota(servicio="bano", tamano="pequeno",
                                            extras=["servicio_inmediato"])])
            )

    def test_toda_cotizacion_exige_aprobacion_humana(self):
        c = self.motor.cotizar(Solicitud(mascotas=[Mascota(servicio="bano", tamano="pequeno")]))
        self.assertTrue(c["requiere_aprobacion_humana"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
