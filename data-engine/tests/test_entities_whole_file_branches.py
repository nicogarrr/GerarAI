"""Ramas de app/models/entities.py que ningun test sin PG recorria.

Sin base de datos: funciones y listeners se llaman directos con objetos
transitorios. Cubre ibkr_raw_row_keys y su listener, las propiedades de
procedencia de FinancialFact y los guards de FactAnchor (constructor cerrado,
from_spec, re-verificacion al insertar, DML masivo).
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, insert, select, update

from app.models.entities import (
    Document,
    FactAnchor,
    FinancialFact,
    _fact_anchor_no_bulk_dml,
    _fact_anchor_revalidate_on_insert,
    _fill_ibkr_raw_row_keys,
    ibkr_raw_row_keys,
)
from app.services.fact_anchor import FactAnchorError, build_anchor

BODY = (
    "Item 1.01. Entry into a Material Definitive Agreement.\n"
    "Alpha will receive $54.20 in cash for each share of Beta common stock.\n"
)
QUOTE = "Alpha will receive $54.20 in cash for each share of Beta common stock."


def _spec(**over):
    args = dict(
        body=BODY,
        accession="0001193125-26-004321",
        filename="d1.htm",
        field="offer_price",
        value_text="$54.20",
        label="OFICIAL",
        quote=QUOTE,
        extractor="test-1.0",
    )
    args.update(over)
    return build_anchor(**args)


# --- ibkr_raw_row_keys y su listener ---------------------------------------


def test_ibkr_keys_lee_symbol_y_fecha():
    sym, day = ibkr_raw_row_keys({"symbol": "AAPL", "reportDate": "20260105"})
    assert (sym, day) == ("AAPL", date(2026, 1, 5))


def test_ibkr_keys_ilegible_queda_en_none():
    assert ibkr_raw_row_keys(None) == (None, None)
    assert ibkr_raw_row_keys({"symbol": 7, "reportDate": "no-fecha"}) == (None, None)
    assert ibkr_raw_row_keys({"symbol": "X" * 65}) == (None, None)


def test_ibkr_keys_usa_asofdate_y_corta_en_punto_y_coma():
    _, day = ibkr_raw_row_keys({"asOfDate": "2026-02-03;120000"})
    assert day == date(2026, 2, 3)


def test_listener_rellena_lo_que_falta():
    row = SimpleNamespace(
        payload={"symbol": "MSFT", "reportDate": "20260105"},
        symbol=None,
        report_date=None,
    )
    _fill_ibkr_raw_row_keys(None, None, row)
    assert row.symbol == "MSFT"
    assert row.report_date == date(2026, 1, 5)


def test_listener_no_pisa_valores_ya_puestos():
    row = SimpleNamespace(
        payload={"symbol": "MSFT", "reportDate": "20260105"},
        symbol="OTRO",
        report_date=date(2020, 1, 1),
    )
    _fill_ibkr_raw_row_keys(None, None, row)
    assert row.symbol == "OTRO"
    assert row.report_date == date(2020, 1, 1)


# --- procedencia de FinancialFact ------------------------------------------


def test_financialfact_sin_documento_no_inventa_procedencia():
    fact = FinancialFact()
    assert fact.source is None
    assert fact.source_url is None
    assert fact.source_title is None
    assert fact.source_published_at is None


def test_financialfact_con_documento_expone_url_titulo_y_fecha():
    published = datetime(2026, 3, 1, 12, 0)
    fact = FinancialFact()
    fact.source = Document(
        source_url="https://www.sec.gov/ix?doc=1", title="10-K", published_at=published
    )
    assert fact.source_url == "https://www.sec.gov/ix?doc=1"
    assert fact.source_title == "10-K"
    assert fact.source_published_at == published


# --- FactAnchor: constructor cerrado, from_spec, listeners -----------------


def test_factanchor_constructor_directo_prohibido():
    with pytest.raises(FactAnchorError, match="from_spec"):
        FactAnchor(tenant_id=1)


def test_from_spec_verificado_retiene_body_y_copia_el_spec():
    spec = _spec()
    anchor = FactAnchor.from_spec(spec, body=BODY, tenant_id=1, company_id=2)
    assert anchor.accession_number == spec.accession
    assert anchor.quote_offset == spec.quote_offset
    assert anchor.company_id == 2
    assert anchor._verified_body == BODY


def test_from_spec_rechaza_spec_que_no_verifica_contra_el_body():
    with pytest.raises(FactAnchorError, match="no verifica"):
        FactAnchor.from_spec(_spec(), body=BODY + "x" * 5, tenant_id=1)
    with pytest.raises(FactAnchorError, match="no verifica"):
        FactAnchor.from_spec(_spec(), body="otro documento", tenant_id=1)


def test_before_insert_acepta_fila_intacta():
    anchor = FactAnchor.from_spec(_spec(), body=BODY, tenant_id=1)
    _fact_anchor_revalidate_on_insert(None, None, anchor)


def test_before_insert_rechaza_fila_sin_body_retenido():
    anchor = FactAnchor.from_spec(_spec(), body=BODY, tenant_id=1)
    del anchor._verified_body
    with pytest.raises(FactAnchorError, match="sin body verificado"):
        _fact_anchor_revalidate_on_insert(None, None, anchor)


def test_before_insert_rechaza_fila_mutada_tras_verificar():
    anchor = FactAnchor.from_spec(_spec(), body=BODY, tenant_id=1)
    anchor.value_text = "$99.99"
    with pytest.raises(FactAnchorError, match="modificada"):
        _fact_anchor_revalidate_on_insert(None, None, anchor)


def _state(statement):
    return SimpleNamespace(statement=statement)


def test_dml_masivo_sobre_fact_anchors_prohibido():
    for stmt in (update(FactAnchor).values(field="x"), delete(FactAnchor)):
        with pytest.raises(FactAnchorError, match="DML masivo"):
            _fact_anchor_no_bulk_dml(_state(stmt))


def test_dml_sobre_otras_tablas_y_selects_pasan():
    _fact_anchor_no_bulk_dml(_state(select(FactAnchor)))
    _fact_anchor_no_bulk_dml(_state(insert(Document).values(title="t")))
    _fact_anchor_no_bulk_dml(_state(update(Document).values(title="t")))
    _fact_anchor_no_bulk_dml(_state(SimpleNamespace(table=None)))


def test_listeners_append_only_de_fact_anchors():
    from app.models.entities import _fact_anchor_no_delete, _fact_anchor_no_update

    with pytest.raises(FactAnchorError, match="UPDATE"):
        _fact_anchor_no_update(None, None, object())
    with pytest.raises(FactAnchorError, match="DELETE"):
        _fact_anchor_no_delete(None, None, object())
