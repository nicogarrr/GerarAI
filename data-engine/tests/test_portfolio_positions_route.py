"""GET /api/portfolio/positions con response_model: el wire es el contrato.

La ruta devolvia schema free-form y el front tipaba a mano: name, sector y
source llegaban sin tipo, y market_value_native estaba tipado como number
aunque la rama de valoracion en suspenso lo emite como null. Estos tests
ejercitan la respuesta HTTP real con el servicio real (sin mock del
payload): posicion valorada, valoracion en suspenso y precio del ledger
sin cotizacion (quote_missing anula las plusvalias).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, IbkrRawRow, Portfolio, Position, Tenant, Transaction, WorkflowRun
from app.schemas.api import PortfolioPositionItemOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-positions-route-test-secret-32-chars"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"portfolio-positions-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Portfolio positions route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "portfolio-positions-user"


def _seed(tenant: str) -> None:
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    valued = Company(
        ticker="VAL", name="Valued Co", exchange="BME", currency="EUR",
        sector="Tech", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    held = Company(
        ticker="HELD", name="Held Co", exchange="BME", currency="EUR",
        sector="Tech", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    ledger = Company(
        ticker="LED", name="Ledger Co", exchange="BME", currency="EUR",
        sector="Tech", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add_all([valued, held, ledger])
    db.commit()
    db.add_all([
        Position(
            company_id=valued.id, quantity=Decimal("100"), currency="EUR",
            average_cost=Decimal("8"), market_price=Decimal("10"),
            market_value=Decimal("1000"), unrealized_pnl=Decimal("200"),
            realized_pnl=Decimal("5"), market_value_native=Decimal("1000"),
            market_value_base=Decimal("1000"), cost_basis_native=Decimal("800"),
            cost_basis_base=Decimal("800"), unrealized_pnl_base=Decimal("200"),
            realized_pnl_base=Decimal("5"), as_of=date(2026, 10, 30),
        ),
        Position(
            company_id=held.id, quantity=Decimal("10"), currency="EUR",
            average_cost=Decimal("50"), market_price=Decimal("60"),
            market_value=Decimal("600"), unrealized_pnl=Decimal("100"),
            realized_pnl=Decimal("0"), as_of=date(2026, 10, 30),
            valuation_hold_reason="split_pending",
            valuation_hold_effective_date=date(2026, 10, 1),
            valuation_hold_since=date(2026, 9, 15),
        ),
        Position(
            company_id=ledger.id, quantity=Decimal("100"), currency="EUR",
            average_cost=Decimal("10"), market_price=Decimal("10"),
            market_value=Decimal("1000"), unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"), source="postgres_ledger",
            cost_basis_native=Decimal("1000"), cost_basis_base=Decimal("1000"),
            unrealized_pnl_base=Decimal("0"),
            as_of=date(2026, 10, 30),
        ),
        Transaction(
            company_id=ledger.id, trade_date=date(2026, 1, 15), action="buy",
            quantity=Decimal("100"), price=Decimal("10"), fees=Decimal("0"),
            currency="EUR",
        ),
    ])
    db.commit()
    # Analisis tracked para VAL: thesis_status != insufficient_data, asi que
    # el servicio omite missing_inputs (el wire debe conservar la omision).
    db.add(WorkflowRun(
        workflow_name="GenerateThesisWorkflow", status="succeeded",
        input_payload={"ticker": "VAL"}, result_payload={"status": "ok"},
    ))
    db.commit()
    db.close()


def _ibkr_company(db, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=f"{ticker} Co", exchange="NYSE", currency="USD",
        sector="Tech", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _ibkr_position(company_id: int, quantity: str, cost_native: str) -> Position:
    return Position(
        company_id=company_id, quantity=Decimal(quantity), currency="USD",
        average_cost=Decimal("130"), market_price=Decimal("130"),
        market_value=Decimal(quantity) * Decimal("130"),
        unrealized_pnl=Decimal("0"), realized_pnl=Decimal("0"),
        source="ibkr_flex", cost_basis_native=Decimal(cost_native),
        statement_as_of=date(2026, 10, 28), as_of=date(2026, 10, 28),
    )


def _seed_ibkr(db) -> None:
    """Tres posiciones ibkr_flex para las tres ramas del reconciliador."""
    ok_co = _ibkr_company(db, "IBKOK")
    db.add(_ibkr_position(ok_co.id, "8", "1040"))  # 8 * 130
    db.add(Transaction(
        company_id=ok_co.id, trade_date=date(2026, 10, 28), action="buy",
        quantity=Decimal("8"), price=Decimal("130"), fees=Decimal("0"),
        currency="USD", raw_payload={"tradeID": "t-ok", "accountId": "U1"},
    ))
    db.add(IbkrRawRow(
        account_id="U1", section="OpenPositions", path="OpenPosition",
        row_hash="a" * 64, symbol="IBKOK", report_date=date(2026, 10, 28),
        payload={
            "symbol": "IBKOK", "reportDate": "2026-10-28", "position": "8",
            "costBasisPrice": "130", "currency": "USD",
            "costBasisCurrency": "USD", "levelOfDetail": "SUMMARY",
        },
    ))
    db.commit()
    review_co = _ibkr_company(db, "IBKREV")
    # El extracto fija 8 * 137.5 = 1100 pero el ledger nativo suma 8 * 130:
    # delta 60 > tolerancia -> review_required.
    db.add(_ibkr_position(review_co.id, "8", "1100"))
    db.add(Transaction(
        company_id=review_co.id, trade_date=date(2026, 10, 28), action="buy",
        quantity=Decimal("8"), price=Decimal("130"), fees=Decimal("0"),
        currency="USD", raw_payload={"tradeID": "t-rev", "accountId": "U1"},
    ))
    db.add(IbkrRawRow(
        account_id="U1", section="OpenPositions", path="OpenPosition",
        row_hash="b" * 64, symbol="IBKREV", report_date=date(2026, 10, 28),
        payload={
            "symbol": "IBKREV", "reportDate": "2026-10-28", "position": "8",
            "costBasisPrice": "137.5", "currency": "USD",
            "costBasisCurrency": "USD", "levelOfDetail": "SUMMARY",
        },
    ))
    db.commit()
    not_co = _ibkr_company(db, "IBKNOT")
    # Sin operaciones nativas: not_comparable (no_native_trades).
    db.add(_ibkr_position(not_co.id, "5", "500"))
    db.commit()


def test_positions_empty_portfolio_validates_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/positions")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["items"] == []
    assert payload["page_info"]["total_items"] == 0


def test_positions_full_wire_with_real_service(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)
    _seed(tenant)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/positions")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["page_info"]["total_items"] == 3
    items = {item["ticker"]: item for item in payload["items"]}
    for item in items.values():
        PortfolioPositionItemOut.model_validate(item)

    valued = items["VAL"]
    assert valued["name"] == "Valued Co"  # clave sin tipo en el front
    assert valued["sector"] == "Tech"     # clave sin tipo en el front
    assert valued["source"] == "manual"   # clave sin tipo en el front
    assert valued["market_price"] == 10.0
    assert valued["unrealized_pnl"] == 200.0
    assert valued["cost_basis"] == 800.0
    assert valued["market_value_native"] == 1000.0
    assert valued["quote_missing"] is False
    assert valued["valuation_hold"] is None
    assert valued["cost_reconciliation"] is None
    assert valued["fiscal_bucket"] is None  # sin compras registradas

    held = items["HELD"]
    assert held["market_price"] is None
    assert held["market_value"] is None
    # market_value_native: null en suspenso (el front lo tipaba como number).
    assert held["market_value_native"] is None
    assert held["unrealized_pnl"] is None
    assert held["valuation_hold"] == {
        "reason": "split_pending",
        "effective_date": "2026-10-01",
        "since": "2026-09-15",
    }

    # Analisis tracked real: thesis_status ok -> el servicio omite
    # missing_inputs y el wire conserva la omision (sin null anadido).
    analysis = valued["analysis"]
    assert analysis is not None
    assert analysis["status"] == "succeeded"
    assert analysis["thesis_status"] == "ok"
    assert "missing_inputs" not in analysis

    ledger = items["LED"]
    # Precio del ledger sin cotizacion: plusvalias null, nunca un 0 medido.
    assert ledger["quote_missing"] is True
    assert ledger["unrealized_pnl"] is None
    assert ledger["unrealized_pnl_base"] is None
    assert ledger["pnl_price_effect_base"] is None
    assert ledger["first_buy_date"] == "2026-01-15"
    assert ledger["holding_days"] is not None
    assert ledger["fiscal_bucket"] in ("corto_plazo", "largo_plazo")


def test_positions_ibkr_cost_reconciliation_branches(monkeypatch) -> None:
    """Ramas reales del reconciliador IBKR: ok / review_required /
    not_comparable, y el wire conserva las omisiones de cada rama."""
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    db.commit()
    _seed_ibkr(db)
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/positions")

    assert res.status_code == 200, res.text
    items = {item["ticker"]: item for item in res.json()["items"]}
    for ticker in ("IBKOK", "IBKREV", "IBKNOT"):
        PortfolioPositionItemOut.model_validate(items[ticker])

    ok = items["IBKOK"]["cost_reconciliation"]
    assert ok["status"] == "ok"
    assert ok["reason"] is None
    assert ok["snapshot_cost_native"] == 1040.0
    assert ok["trade_cost_native"] == 1040.0
    assert ok["difference_native"] == 0.0
    assert ok["currency"] == "USD"
    assert ok["cost_unit_verified"] is True
    # ok sin conflicto: los costes no se enmascaran.
    assert items["IBKOK"]["average_cost"] == 130.0

    review = items["IBKREV"]["cost_reconciliation"]
    assert review["status"] == "review_required"
    assert review["reason"] == "ibkr_cost_mismatch"
    assert review["difference_native"] == 60.0
    assert review["message"]
    # En revision el coste/plusvalia conflictivos no se devuelven como hechos.
    assert items["IBKREV"]["average_cost"] is None
    assert items["IBKREV"]["cost_basis"] is None

    not_comp = items["IBKNOT"]["cost_reconciliation"]
    assert not_comp["status"] == "not_comparable"
    assert not_comp["reason"] == "no_native_trades"
    assert not_comp["message"]
    # Rama not_comparable: el servicio omite los importes; el wire NO los
    # rellena con null (response_model_exclude_unset=True).
    for key in (
        "snapshot_cost_native", "trade_cost_native", "difference_native",
        "tolerance_native", "currency", "cost_unit_verified",
    ):
        assert key not in not_comp
