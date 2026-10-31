"""Comisiones en la importación CSV: nunca se pierden en silencio.

Los extractos de broker (DEGIRO, entre otros) exportan los costes de la
operación como importe NEGATIVO ("-2,00"). Antes la vista previa los convertía
en 0 sin avisar, y la compra entraba en cartera con un coste de adquisición
menor que el real (art. 35 LIRPF: las comisiones forman parte del valor de
adquisición), inflando la ganancia que se declara al vender.
"""

from __future__ import annotations

from app.services.transaction_import_service import TransactionImportService


def _csv(*rows: str) -> bytes:
    header = "ticker;date;action;quantity;price;fees;currency"
    return "\n".join([header, *rows]).encode("utf-8")


def test_comision_negativa_del_broker_se_importa_como_coste():
    result = TransactionImportService().preview_import(
        _csv("SAN.MC;2024-01-15;compra;100;3,50;-2,00;EUR"), "degiro.csv"
    )
    assert result.success is True
    assert result.preview_items[0].fees == 2.0


def test_comision_no_numerica_es_error_de_fila_no_cero():
    result = TransactionImportService().preview_import(
        _csv("SAN.MC;2024-01-15;compra;100;3,50;2,00 EUR;EUR"), "x.csv"
    )
    assert result.success is False
    assert result.preview_items == []
    assert [(e.row_number, e.field) for e in result.errors] == [(2, "fees")]
    assert result.errors[0].raw_value == "2,00 EUR"


def test_comision_vacia_sigue_siendo_cero():
    result = TransactionImportService().preview_import(
        _csv("SAN.MC;2024-01-15;compra;100;3,50;;EUR"), "x.csv"
    )
    assert result.success is True
    assert result.preview_items[0].fees == 0.0


def test_ingreso_de_efectivo_se_avisa_y_no_entra_en_el_lote():
    """La vista previa no puede dar por buena una fila que el ledger rechaza al confirmar."""
    from app.services.portfolio_ledger_service import LEDGER_ACTIONS

    result = TransactionImportService().preview_import(
        _csv(
            ";2024-01-10;Ingreso;1;1000;;EUR",
            "SAN.MC;2024-01-15;compra;100;3,50;1,00;EUR",
            ";2024-02-01;Retirada;1;200;;EUR",
        ),
        "extracto.csv",
    )
    assert result.success is True
    assert [i.row_number for i in result.preview_items] == [3]
    assert all(i.action in LEDGER_ACTIONS for i in result.preview_items)
    assert [(w.row_number, w.field) for w in result.warnings] == [(2, "action"), (4, "action")]
    assert "efectivo" in result.warnings[0].message


def test_fichero_con_fechas_americanas_lee_todas_como_mes_dia():
    """Si una fila solo cabe como MM/DD (12/31/2024), el fichero es americano:
    las ambiguas (03/04/2024) son 4 de marzo, no 3 de abril."""
    result = TransactionImportService().preview_import(
        _csv(
            "AAPL;03/04/2024;buy;10;170.00;1.00;USD",
            "AAPL;12/31/2024;sell;5;250.00;1.00;USD",
        ),
        "us.csv",
    )
    assert result.success is True
    assert [i.date for i in result.preview_items] == ["2024-03-04", "2024-12-31"]
    assert not any("día/mes/año" in w.message for w in result.warnings)


def test_fichero_espanol_sigue_leyendo_dia_mes():
    result = TransactionImportService().preview_import(
        _csv(
            "SAN.MC;03/04/2024;compra;10;3,50;1,00;EUR",
            "SAN.MC;31/12/2024;venta;5;4,00;1,00;EUR",
        ),
        "es.csv",
    )
    assert [i.date for i in result.preview_items] == ["2024-04-03", "2024-12-31"]
