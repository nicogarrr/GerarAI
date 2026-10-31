"""GET /api/portfolio/risk-matrix con response_model: el wire es el contrato.

Servicio real sobre SQLite (harness _client + signed_request), sin mock del
payload. Cubre: matriz ok con 3 posiciones (una USD convertida con FX),
exclusiones declaradas (historia corta, FX inexistente), ausencia de claves
de riesgo en posiciones excluidas (exclude_unset), warning FX visible para
la UI y tenant sin posiciones. Tickers RMT* (unicos por fichero: los tests
comparten la DB real de SessionLocal/init_db y el ticker es UNIQUE).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, FXRate, Portfolio, Position, Tenant
from app.schemas.api import PortfolioRiskMatrixOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "portfolio-risk-matrix-route-secret-32"

DAYS = 75  # 74 retornos diarios >= MIN_MATRIX_SESSIONS (60)


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"risk-matrix-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Risk matrix route test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "risk-matrix-user"


def _seed(monkeypatch) -> tuple[TestClient, str, str]:
    from app.models import MarketPrice

    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    suffix = uuid4().hex[:4].upper()
    tickers = {
        "a": f"RA{suffix}",
        "b": f"RB{suffix}",
        "c": f"RC{suffix}",
        "d": f"RD{suffix}",
        "e": f"RE{suffix}",
    }
    companies = {}
    for key, (ticker, currency) in {
        "a": (tickers["a"], "EUR"),
        "b": (tickers["b"], "EUR"),
        "c": (tickers["c"], "USD"),
        "d": (tickers["d"], "EUR"),
        "e": (tickers["e"], "GBP"),
    }.items():
        company = Company(
            ticker=ticker, name=f"RM {key}", exchange="X", currency=currency,
            sector="Tech", industry="I", company_type="holding",
            valuation_model="unassigned", special_sources=[], special_risks=[],
            factor_tags=[],
        )
        db.add(company)
        companies[key] = company
    db.commit()
    today = date.today()
    start = today - timedelta(days=DAYS - 1)
    for key in companies:
        db.refresh(companies[key])
    # Series deterministicas no degeneradas (fases distintas por activo).
    def price(key: str, i: int) -> float:
        base = {"a": 100.0, "b": 80.0, "c": 50.0, "d": 40.0, "e": 60.0}[key]
        drift = {"a": 0.0011, "b": 0.0007, "c": 0.0009, "d": 0.001, "e": 0.0008}[key]
        phase = {"a": 0.0, "b": 1.1, "c": 2.3, "d": 0.7, "e": 1.9}[key]
        import math

        return base * (1 + drift) ** i + 0.8 * math.sin(i / 3.0 + phase)

    def add_prices(key: str, days: int) -> None:
        cid = companies[key].id
        for i in range(days):
            day = start + timedelta(days=i)
            value = round(price(key, i), 4)
            db.add(MarketPrice(
                company_id=cid, date=day,
                open=Decimal(str(value)), high=Decimal(str(value)),
                low=Decimal(str(value)), close=Decimal(str(value)),
                adj_close=Decimal(str(value)), source="probe",
            ))

    for key in ("a", "b", "c", "e"):
        add_prices(key, DAYS)
    add_prices("d", 30)  # historia corta: excluida por minimo de muestra
    # FX USD->EUR diario con carry-forward desde ANTES del primer precio.
    for i in range(-10, DAYS, 3):
        day = start + timedelta(days=i)
        db.add(FXRate(
            base_currency="EUR", quote_currency="USD",
            rate=Decimal("0.92"), rate_date=day, source="probe",
        ))
    for key, value in {"a": "5000", "b": "3000", "c": "2000", "d": "1000", "e": "1000"}.items():
        company = companies[key]
        currency = company.currency
        db.add(Position(
            company_id=company.id, quantity=Decimal("10"), average_cost=Decimal("100"),
            market_price=Decimal("100"), market_value=Decimal(value),
            unrealized_pnl=Decimal("0"), realized_pnl=Decimal("0"), currency=currency,
            base_currency="EUR", market_value_native=Decimal(value),
            cost_basis_native=Decimal(value), market_value_base=Decimal(value),
            cost_basis_base=Decimal(value), as_of=today, source="probe",
        ))
    db.commit()
    db.close()
    return client, tenant, user


def test_risk_matrix_ok_with_fx_conversion(monkeypatch) -> None:
    client, tenant, user = _seed(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/risk-matrix")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioRiskMatrixOut.model_validate(payload)
    assert payload["status"] == "ok"
    assert payload["base_currency"] == "EUR"
    assert payload["estimator"]["name"] == "ledoit_wolf_identity"
    assert 0.0 <= payload["estimator"]["shrinkage"] <= 1.0
    assert payload["window"]["sessions_common"] >= 60

    included = {p["ticker"]: p for p in payload["positions"] if p["included"]}
    assert len(included) == 3  # RA/RB EUR directas + RC USD convertida
    usd = next(p for p in included.values() if p["fx_mode"] == "converted")
    assert usd["fx_mode"] == "converted"
    contributions = [p["risk_contribution"] for p in included.values()]
    assert abs(sum(contributions) - 1.0) < 1e-4
    for entry in included.values():
        assert "excluded_reason" not in entry
        assert entry["vol_annualized"] is not None
        assert entry["sessions_common"] == payload["window"]["sessions_common"]

    grid = payload["covariance_annualized"]
    n = len(grid["tickers"])
    assert n == 3
    assert all(len(row) == n for row in grid["matrix"])
    corr = payload["correlation"]
    assert corr["source"] == "shrunk_covariance"
    for i in range(n):
        assert abs(corr["matrix"][i][i] - 1.0) < 1e-6
    assert payload["portfolio"]["vol_annualized"] > 0

    # El aviso FX llega a la UI (regla de Nico: la limitacion se VE).
    assert any(w["code"] == "fx_conversion" for w in payload["warnings"])

    # Excluidas: RD historia corta, RE sin historico FX. Motivos declarados.
    reasons = {item["ticker"]: item["reason"] for item in payload["excluded"]}
    assert len(reasons) == 2
    assert set(reasons.values()) == {"insufficient_history", "fx_history_insufficient"}


def test_risk_matrix_absence_keys_on_excluded_positions(monkeypatch) -> None:
    client, tenant, user = _seed(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/risk-matrix")

    assert res.status_code == 200, res.text
    payload = res.json()
    excluded_entries = [p for p in payload["positions"] if not p["included"]]
    assert len(excluded_entries) == 2
    for entry in excluded_entries:
        # Sin numeros de riesgo fabricados: las claves NO existen (exclude_unset),
        # y el motivo de exclusion si.
        assert "vol_annualized" not in entry
        assert "risk_contribution" not in entry
        assert "marginal_contribution" not in entry
        assert "weight_included" not in entry
        assert entry["excluded_reason"] in {
            "insufficient_history",
            "fx_history_insufficient",
        }


def test_risk_matrix_without_positions(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/risk-matrix")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioRiskMatrixOut.model_validate(payload)
    assert payload["status"] == "no_positions"
    assert payload["covariance_annualized"] is None
    assert payload["correlation"] is None
    assert payload["portfolio"] is None
    assert payload["positions"] == []


def test_risk_matrix_pairwise_fallback_below_min_sessions(monkeypatch) -> None:
    """Con 40 sesiones (>= 20 Pearson pero < 60 de matriz): matrices N/D,
    correlacion por pares declarada y warning visible para la UI."""
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    import math

    from app.models import MarketPrice

    suffix = uuid4().hex[:4].upper()
    today = date.today()
    start = today - timedelta(days=39)
    for key, phase in (("a", 0.0), ("b", 1.3)):
        company = Company(
            ticker=f"RF{key.upper()}{suffix}", name=f"RF {key}", exchange="X",
            currency="EUR", sector="Tech", industry="I", company_type="holding",
            valuation_model="unassigned", special_sources=[], special_risks=[],
            factor_tags=[],
        )
        db.add(company)
        db.commit()
        db.refresh(company)
        for i in range(40):
            day = start + timedelta(days=i)
            value = round(100.0 * (1.001) ** i + 0.6 * math.sin(i / 2.7 + phase), 4)
            db.add(MarketPrice(
                company_id=company.id, date=day,
                open=Decimal(str(value)), high=Decimal(str(value)),
                low=Decimal(str(value)), close=Decimal(str(value)),
                adj_close=Decimal(str(value)), source="probe",
            ))
        db.add(Position(
            company_id=company.id, quantity=Decimal("10"), average_cost=Decimal("100"),
            market_price=Decimal("100"), market_value=Decimal("1000"),
            unrealized_pnl=Decimal("0"), realized_pnl=Decimal("0"), currency="EUR",
            base_currency="EUR", market_value_native=Decimal("1000"),
            cost_basis_native=Decimal("1000"), market_value_base=Decimal("1000"),
            cost_basis_base=Decimal("1000"), as_of=today, source="probe",
        ))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/risk-matrix")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioRiskMatrixOut.model_validate(payload)
    assert payload["status"] == "insufficient_history"
    assert payload["covariance_annualized"] is None
    assert payload["portfolio"] is None
    assert payload["estimator"] is None
    correlation = payload["correlation"]
    assert correlation["source"] == "pearson_pairwise_min_20"
    assert len(correlation["tickers"]) == 2
    assert correlation["matrix"][0][1] is not None
    assert any(w["code"] == "pairwise_fallback" for w in payload["warnings"])
    # Todas las posiciones declaradas como excluidas de la matriz.
    assert all(not p["included"] for p in payload["positions"])
    assert all("risk_contribution" not in p for p in payload["positions"])


def test_risk_matrix_calendar_misaligned_excluded(monkeypatch) -> None:
    """Regresion (review piloto): 3 activos, dos con >=60 sesiones comunes y
    uno con calendario TOTALMENTE disjunto. La seleccion leave-one-out debe
    expulsar al disjunto con motivo declarado y conservar a los otros dos;
    antes la interseccion vacia empataba a todos y nadie salia."""
    client, tenant, user = _client(monkeypatch)
    db = SessionLocal()
    tenant_row = db.query(Tenant).filter(Tenant.external_id == tenant).one()
    db.info["tenant_id"] = tenant_row.id
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    import math

    from app.models import MarketPrice

    suffix = uuid4().hex[:4].upper()
    today = date.today()
    # A y B: dias 0..74. C: dias 200..274 (disjunto con A y B).
    windows = {
        "a": (today - timedelta(days=74), DAYS),
        "b": (today - timedelta(days=74), DAYS),
        "c": (today - timedelta(days=274), DAYS),
    }
    tickers = {}
    for key, phase in (("a", 0.0), ("b", 1.3), ("c", 2.1)):
        company = Company(
            ticker=f"RG{key.upper()}{suffix}", name=f"RG {key}", exchange="X",
            currency="EUR", sector="Tech", industry="I", company_type="holding",
            valuation_model="unassigned", special_sources=[], special_risks=[],
            factor_tags=[],
        )
        db.add(company)
        db.commit()
        db.refresh(company)
        tickers[key] = company.ticker
        start, days = windows[key]
        for i in range(days):
            day = start + timedelta(days=i)
            value = round(100.0 * (1.001) ** i + 0.6 * math.sin(i / 2.7 + phase), 4)
            db.add(MarketPrice(
                company_id=company.id, date=day,
                open=Decimal(str(value)), high=Decimal(str(value)),
                low=Decimal(str(value)), close=Decimal(str(value)),
                adj_close=Decimal(str(value)), source="probe",
            ))
        db.add(Position(
            company_id=company.id, quantity=Decimal("10"), average_cost=Decimal("100"),
            market_price=Decimal("100"), market_value=Decimal("1000"),
            unrealized_pnl=Decimal("0"), realized_pnl=Decimal("0"), currency="EUR",
            base_currency="EUR", market_value_native=Decimal("1000"),
            cost_basis_native=Decimal("1000"), market_value_base=Decimal("1000"),
            cost_basis_base=Decimal("1000"), as_of=today, source="probe",
        ))
    db.commit()
    db.close()

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/portfolio/risk-matrix")

    assert res.status_code == 200, res.text
    payload = res.json()
    PortfolioRiskMatrixOut.model_validate(payload)
    assert payload["status"] == "ok"
    included = {p["ticker"] for p in payload["positions"] if p["included"]}
    assert included == {tickers["a"], tickers["b"]}
    # El disjunto queda excluido con motivo declarado (nunca silenciado).
    reasons = {item["ticker"]: item["reason"] for item in payload["excluded"]}
    assert reasons == {tickers["c"]: "calendar_misaligned"}
    entry = next(p for p in payload["positions"] if p["ticker"] == tickers["c"])
    assert entry["included"] is False
    assert entry["excluded_reason"] == "calendar_misaligned"
    assert payload["window"]["sessions_common"] >= 60
