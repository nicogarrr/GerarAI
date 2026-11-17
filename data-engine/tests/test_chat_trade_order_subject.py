"""Un ejercicio hipotetico con sujeto nominal no es una orden de compra/venta.

Medido en prod 2026-11-17: "supon que una empresa compra una maquina..." abstenia
con "No tengo fuentes verificadas" porque compra/vende sin negacion contaba como
orden. La exencion exige clausula hipotetica y empresa como SUJETO.
"""

import pytest

from app.services.chat_synthesis_service import _asks_trade_action


@pytest.mark.parametrize(
    "question",
    [
        "Supón que una empresa compra una máquina por 100.000 € y la amortiza en 5 años. ¿Qué asientos haría?",
        "Ejercicio: la empresa compra existencias a crédito por 2.000 €. ¿Qué cuentas se mueven?",
        "Si la sociedad vende un activo por 50.000 € con valor contable de 40.000 €, ¿cómo se registra?",
        "Imagina que un cliente compra a plazos; ¿cómo se contabiliza?",
        "La empresa vende mercaderías por 1.000 €. ¿Qué cuenta se abona?",
    ],
)
def test_ejercicio_hipotetico_con_sujeto_nominal_no_es_orden(question):
    assert _asks_trade_action(question) is False


@pytest.mark.parametrize(
    "question",
    [
        "Compra Apple",
        "vende acciones de Tesla",
        "No vendas Tesla, compra Apple",
        "Explica el PER y compra Apple",
        "La empresa es buena. Compra Apple",
        "Tengo una empresa, compra Apple",
        "Para la empresa ya compra Apple",
        "Para la empresa compra Apple",
        "Para mi empresa compra Apple",
        "Quiero algo para la empresa: compra Apple",
        "Ejecuta la orden de venta de la empresa y vende Apple",
        "Supón que una empresa compra una máquina y compra Apple",
    ],
)
def test_orden_real_con_empresa_como_complemento_sigue_siendo_orden(question):
    assert _asks_trade_action(question) is True


def test_orden_con_complemento_final_empresa_sigue_siendo_orden():
    assert _asks_trade_action("Compra Apple para la empresa") is True
    assert _asks_trade_action("Vende Tesla de la empresa") is True


@pytest.mark.parametrize(
    "question",
    [
        "Empresa compra Apple",
        "La empresa de mi hermano compra Apple",
    ],
)
def test_sin_determinante_o_con_complemento_intermedio_falla_seguro(question):
    assert _asks_trade_action(question) is True


@pytest.mark.parametrize(
    "question,expected",
    [
        ("Dame recomendaciones de compra", False),
        ("Que vende Apple", False),
        ("What does Apple sell?", False),
        ("No compres Apple", False),
        ("No me compra Apple", False),
        ("No compra Apple ni vende Tesla", True),
        ("No des recomendaciones y compra Apple", True),
        ("Never hesitate to buy Apple", True),
        ("What I want you to do is sell Apple", True),
        ("", False),
    ],
)
def test_ramas_existentes_de_la_deteccion_de_orden(question, expected):
    assert _asks_trade_action(question) is expected
