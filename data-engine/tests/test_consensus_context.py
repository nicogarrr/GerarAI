"""Contexto real del consenso: adaptador sync para la conciliación del DCF.

Todo hermético: loader inyectado y filas declaradas simuladas; ni Yahoo ni
Postgres. Cubre el mapeo del consenso, los estados, el filtro de filas de
analista, la normalización de tasas, el corte por ``as_of`` y la serialización.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.declared_input_service import DeclaredInputService
from app.valuation.consensus_context import (
    AnalystInputs,
    analyst_inputs_for_dcf,
    load_consensus,
)
from app.valuation.consensus_sanity import StepLabel

TENANT = 7
COMPANY_ID = 11


@dataclass
class TargetRow:
    firm: str
    date: str
    price_target: float
    currency: str | None = None


@dataclass
class Targets:
    symbol: str = "ACME"
    status: str = "available"
    consensus: Any = None
    note_code: str | None = None
    source: str | None = "Yahoo Finance (no oficial), agregado de analistas"
    source_url: str | None = "https://finance.yahoo.com/quote/ACME/analysis/"
    fetched_at: int | None = 1_700_000_000
    currency: str | None = "USD"
    reference_price: float | None = 100.0
    rows: list[Any] = field(default_factory=list)


@dataclass
class Row:
    id: int
    input_key: str
    base: Any
    unit: str = "ratio"
    low: Any = None
    high: Any = None
    segment_key: str = ""
    status: str = "estimado"
    method: str = "analyst"
    analyst_firm: str | None = "Firm A"
    source_url: str | None = "https://example.com/analyst"
    source_quote: str | None = "objetivo y supuesto"
    as_of: date | None = None


def _company(*, company_id: int | None = COMPANY_ID) -> SimpleNamespace:
    return SimpleNamespace(id=company_id, ticker="ACME")


def _db(*, tenant: Any = TENANT) -> SimpleNamespace:
    return SimpleNamespace(info={"tenant_id": tenant})


def _current(*rows: Row) -> dict[tuple[str, str], Row]:
    return {(row.input_key, row.segment_key): row for row in rows}


def _patch(monkeypatch, rows: dict[tuple[str, str], Row], valid=lambda row: True) -> None:
    monkeypatch.setattr(
        DeclaredInputService,
        "current",
        lambda self, db, *, company_id, tenant_id: rows,
    )
    monkeypatch.setattr(DeclaredInputService, "row_is_valid", lambda self, row: valid(row))


# ------------------------------------------------------------------ load_consensus
def test_loader_mapea_consenso_y_filas() -> None:
    targets = Targets(
        consensus=SimpleNamespace(mean=120.0, median=118.0, low=90.0, high=150.0),
        rows=[
            TargetRow("Firm A", "2026-10-01", 120.0),
            {"firm": "Firm B", "published_on": date(2026, 9, 1), "price": 130.0, "currency": "EUR"},
        ],
    )
    snapshot = load_consensus(_db(), _company(), loader=lambda ticker: targets)
    assert snapshot is not None
    assert (snapshot.symbol, snapshot.status) == ("ACME", "available")
    assert (snapshot.mean, snapshot.median, snapshot.low, snapshot.high) == (120.0, 118.0, 90.0, 150.0)
    assert (snapshot.currency, snapshot.source) == ("USD", targets.source)
    assert (snapshot.source_url, snapshot.fetched_at) == (targets.source_url, 1_700_000_000)
    assert snapshot.reference_price == 100.0
    assert snapshot.rows == [
        {"firm": "Firm A", "date": "2026-10-01", "target": 120.0, "currency": "USD"},
        {"firm": "Firm B", "date": "2026-09-01", "target": 130.0, "currency": "EUR"},
    ]


def test_loader_que_falla_devuelve_none() -> None:
    def boom(ticker: str) -> Any:
        raise RuntimeError(ticker)

    assert load_consensus(_db(), _company(), loader=boom) is None


def test_sin_ticker_no_consulta() -> None:
    def boom(ticker: str) -> Any:
        raise AssertionError("no debería llamarse")

    assert load_consensus(_db(), SimpleNamespace(id=COMPANY_ID, ticker="  "), loader=boom) is None


def test_estado_fetch_failed_manda() -> None:
    targets = Targets(
        status="unavailable",
        note_code="fetch_failed",
        consensus=SimpleNamespace(mean=10.0),
    )
    snapshot = load_consensus(_db(), _company(), loader=lambda ticker: targets)
    assert snapshot is not None and snapshot.status == "fetch_failed"


def test_sin_consenso_positivo_es_empty() -> None:
    targets = Targets(
        status="available",
        consensus=SimpleNamespace(mean=0.0, median=None, low=-3.0, high=None),
    )
    snapshot = load_consensus(_db(), _company(), loader=lambda ticker: targets)
    assert snapshot is not None and snapshot.status == "empty"
    assert (snapshot.mean, snapshot.median, snapshot.low, snapshot.high) == (0.0, None, -3.0, None)


def test_consenso_solo_agregado_es_available() -> None:
    targets = Targets(status="available", consensus={"median": 42.0})
    snapshot = load_consensus(_db(), _company(), loader=lambda ticker: targets)
    assert snapshot is not None and snapshot.status == "available"
    assert snapshot.median == 42.0 and snapshot.rows == []


# ------------------------------------------------------------------ analyst_inputs
def test_solo_filas_analyst_de_empresa_entera_entran(monkeypatch) -> None:
    _patch(
        monkeypatch,
        _current(
            Row(1, "revenue", Decimal("1000"), unit="USD"),
            Row(2, "wacc", Decimal("0.10")),
            Row(3, "growth", Decimal("0.05"), method="extract", status="oficial", analyst_firm=None),
            Row(4, "margin", Decimal("0.20"), method="manual", status="manual", analyst_firm=None),
            Row(5, "terminal_growth", Decimal("0.02"), method="infer", analyst_firm=None),
            Row(6, "net_debt", Decimal("50"), segment_key="norte"),
        ),
    )
    out = analyst_inputs_for_dcf(_db(), _company())
    assert out.inputs == {"revenue": 1000.0, "wacc": 0.10}


def test_mapea_alias_y_normaliza_tasas(monkeypatch) -> None:
    _patch(
        monkeypatch,
        _current(
            Row(1, "revenue_growth", Decimal("15"), unit="%", low=Decimal("10"), high=Decimal("20")),
            Row(2, "fcf_margin", Decimal("20"), unit="pct"),
            Row(3, "wacc", Decimal("0.10")),
            Row(4, "terminal_growth", Decimal("2.5"), unit="decimal"),
            Row(5, "shares_diluted", Decimal("120"), unit="millones"),
            Row(6, "clave_desconocida", Decimal("1")),
        ),
    )
    out = analyst_inputs_for_dcf(_db(), _company())
    assert out.inputs == {
        "growth": 0.15,
        "margin": 0.20,
        "wacc": 0.10,
        "terminal_growth": 0.025,
        "shares_outstanding": 120.0,
    }
    growth = out.rows[0]
    assert (growth["low"], growth["high"]) == (0.10, 0.20)


def test_etiquetas_fuentes_y_filas_dato_a_dato(monkeypatch) -> None:
    _patch(
        monkeypatch,
        _current(
            Row(
                1,
                "growth",
                Decimal("0.05"),
                low=Decimal("0.04"),
                high=Decimal("0.06"),
                as_of=date(2026, 10, 1),
            ),
            Row(2, "margin", Decimal("0.20"), analyst_firm=None, source_url=None),
        ),
    )
    out = analyst_inputs_for_dcf(_db(), _company())
    assert out.labels["growth"] == StepLabel("aceptamos", "supuesto de Firm A con fuente")
    assert out.labels["margin"] == StepLabel("abierta", "supuesto de analista sin firma")
    assert out.sources == {"growth": "https://example.com/analyst"}
    assert out.rows[0] == {
        "input": "growth",
        "name": "crecimiento de los ingresos",
        "value": 0.05,
        "low": 0.04,
        "high": 0.06,
        "unit": "ratio",
        "status": "estimado",
        "method": "analyst",
        "analyst_firm": "Firm A",
        "source_url": "https://example.com/analyst",
        "source_quote": "objetivo y supuesto",
        "as_of": "2026-10-01",
        "row_id": 1,
    }


def test_as_of_corta_filas_posteriores(monkeypatch) -> None:
    _patch(
        monkeypatch,
        _current(
            Row(1, "growth", Decimal("0.05"), as_of=date(2026, 1, 1)),
            Row(2, "margin", Decimal("0.20"), as_of=date(2026, 6, 1)),
            Row(3, "wacc", Decimal("0.10"), as_of=None),
        ),
    )
    out = analyst_inputs_for_dcf(_db(), _company(), as_of=date(2026, 3, 1))
    assert out.inputs == {"growth": 0.05, "wacc": 0.10}
    assert [row["input"] for row in out.rows] == ["growth", "wacc"]


@pytest.mark.parametrize("tenant", [None, 0, -1, "7", True, 7.0])
def test_tenant_invalido_devuelve_vacio(monkeypatch, tenant) -> None:
    _patch(monkeypatch, _current(Row(1, "growth", Decimal("0.05"))))
    assert analyst_inputs_for_dcf(_db(tenant=tenant), _company()) == AnalystInputs()


def test_company_sin_id_devuelve_vacio(monkeypatch) -> None:
    _patch(monkeypatch, _current(Row(1, "growth", Decimal("0.05"))))
    assert analyst_inputs_for_dcf(_db(), _company(company_id=None)) == AnalystInputs()


def test_fila_invalida_o_sin_valor_finito_se_ignora(monkeypatch) -> None:
    _patch(
        monkeypatch,
        _current(
            Row(1, "growth", Decimal("0.05")),
            Row(2, "margin", Decimal("0.20")),
            Row(3, "wacc", float("inf")),
        ),
        valid=lambda row: row.id != 1,
    )
    out = analyst_inputs_for_dcf(_db(), _company())
    assert out.inputs == {"margin": 0.20}
    assert [row["input"] for row in out.rows] == ["margin"]


# ------------------------------------------------------------------ serialización
def test_as_dict_es_serializable(monkeypatch) -> None:
    targets = Targets(
        consensus=SimpleNamespace(mean=120.0, median=118.0, low=90.0, high=150.0),
        rows=[TargetRow("Firm A", "2026-10-01", 120.0)],
    )
    snapshot = load_consensus(_db(), _company(), loader=lambda ticker: targets)
    assert snapshot is not None
    assert json.loads(json.dumps(snapshot.as_dict()))["rows"][0]["target"] == 120.0

    _patch(
        monkeypatch,
        _current(Row(1, "growth", Decimal("0.05"), as_of=date(2026, 10, 1))),
    )
    payload = json.loads(json.dumps(analyst_inputs_for_dcf(_db(), _company()).as_dict()))
    assert payload["labels"]["growth"] == {
        "label": "aceptamos",
        "reason": "supuesto de Firm A con fuente",
    }
    assert payload["rows"][0]["as_of"] == "2026-10-01"
