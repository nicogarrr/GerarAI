"""Screener conectado a valoracion, tesis y nivel DCA.

Tres nombres nuevos usables en cualquier criterio del motor de screener:
- `margen_seguridad`: margen del motor de valoracion persistido (decimal, 0.25 = 25 %).
- `tiene_tesis` / `tesis_publicada`: 1 o 0.
- `nivel_dca`: nivel del motor DCA (4..1 compra, -1/-2 recorte). Si la tabla
  del motor DCA no existe todavia (rama sin mergear) o el ticker no tiene
  nivel, es un dato AUSENTE: la empresa no casa y el nombre aparece en
  `metrics_without_data`, nunca como un 0 inventado.
"""

from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, ThesisVersion, ValuationModel, ValuationOutput
from app.services.screener_context_metrics import CONTEXT_METRICS, context_observations
from app.services.screener_service import ScreenerService


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker,
        name=f"{ticker} Co",
        exchange="TEST",
        currency="USD",
        sector="Test",
        industry="Test",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _valuation(
    db: Session, company: Company, *, version: int, status: str, mos, convention="discount_to_value_v1"
) -> None:
    model = ValuationModel(
        company_id=company.id, model_type="standard_dcf", version=version, status=status, calculation_trace={}
    )
    db.add(model)
    db.flush()
    db.add(
        ValuationOutput(
            valuation_model_id=model.id,
            scenario="base",
            value_per_share=Decimal("100"),
            output_payload={
                "margin_of_safety": mos,
                "status": status,
                "trace": {"margin_of_safety_convention": convention},
            },
        )
    )
    db.commit()


def _thesis(db: Session, company: Company, status: str, version: int = 1) -> None:
    db.add(
        ThesisVersion(
            company_id=company.id,
            version=version,
            status=status,
            thesis_markdown="# T",
            executive_summary="R",
            rating="watch",
        )
    )
    db.commit()


DCA_DDL = """
CREATE TABLE dca_signal_states (
    id INTEGER PRIMARY KEY, tenant_id INTEGER, symbol VARCHAR(20) NOT NULL,
    company_id INTEGER, level INTEGER NOT NULL, status VARCHAR(20) NOT NULL,
    period VARCHAR(7) NOT NULL, signal_date DATE NOT NULL
)
"""


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _dca(db: Session, symbol: str, level: int, company_id=None) -> None:
    db.add(
        _real_dca_row(
            tenant=db.info.get("tenant_id"),
            symbol=symbol,
            level=level,
            company_id=company_id,
            day=date(2026, 10, 26),
        )
    )
    db.commit()


def test_margin_of_safety_comes_from_latest_engine_valuation(db):
    pool = _company(db, "POOL")
    _valuation(db, pool, version=1, status="final", mos=0.05)
    _valuation(db, pool, version=2, status="final", mos=0.31)
    obs = context_observations(db, {"margen_seguridad"})
    assert obs[pool.id]["margen_seguridad"].value == Decimal("0.31")
    assert "motor de valoración v2" in obs[pool.id]["margen_seguridad"].source


def test_insufficient_latest_valuation_is_missing_not_stale(db):
    uber = _company(db, "UBER")
    _valuation(db, uber, version=1, status="final", mos=0.4)
    _valuation(db, uber, version=2, status="insufficient_data", mos=None)
    obs = context_observations(db, {"margen_seguridad"})
    assert "margen_seguridad" not in obs.get(uber.id, {})


def test_thesis_flags_are_one_or_zero(db):
    a, b, c = _company(db, "AAA"), _company(db, "BBB"), _company(db, "CCC")
    _thesis(db, a, "published")
    _thesis(db, b, "draft")
    _thesis(db, c, "insufficient_data")
    obs = context_observations(db, {"tiene_tesis", "tesis_publicada"})
    assert obs[a.id]["tiene_tesis"].value == 1 and obs[a.id]["tesis_publicada"].value == 1
    assert obs[b.id]["tiene_tesis"].value == 1 and obs[b.id]["tesis_publicada"].value == 0
    # Una tesis sin datos suficientes no cuenta como tesis.
    assert obs[c.id]["tiene_tesis"].value == 0


def test_dca_level_degrades_cleanly_without_the_dca_table(db):
    pool = _company(db, "POOL")
    obs = context_observations(db, {"nivel_dca"})
    assert "nivel_dca" not in obs.get(pool.id, {})
    result = ScreenerService().run(db, criteria=[{"left": "nivel_dca", "operator": ">=", "right": "3"}])
    assert result["match_count"] == 0
    assert result["metrics_without_data"] == ["nivel_dca"]


def test_dca_level_read_by_company_id_or_symbol(db):
    pool, uber, aapl = _company(db, "POOL"), _company(db, "UBER"), _company(db, "AAPL")
    _dca(db, "POOL", 4, company_id=pool.id)
    _dca(db, "UBER", 3)  # sin company_id: se casa por ticker
    obs = context_observations(db, {"nivel_dca"})
    assert obs[pool.id]["nivel_dca"].value == 4
    assert obs[uber.id]["nivel_dca"].value == 3
    assert obs[pool.id]["nivel_dca"].period == "2026-10"
    assert "nivel_dca" not in obs.get(aapl.id, {})


def test_screener_combines_the_three_filters(db):
    pool, uber, aapl = _company(db, "POOL"), _company(db, "UBER"), _company(db, "AAPL")
    for company, mos, level in ((pool, 0.30, 4), (uber, 0.25, 2), (aapl, -0.10, 1)):
        _valuation(db, company, version=1, status="final", mos=mos)
        _thesis(db, company, "published")
        _dca(db, company.ticker, level, company_id=company.id)
    result = ScreenerService().run(
        db,
        criteria=[
            {"left": "margen_seguridad", "operator": ">", "right": "0.2"},
            {"left": "tiene_tesis", "operator": "==", "right": "1"},
            {"left": "nivel_dca", "operator": ">=", "right": "3"},
        ],
    )
    matched = [row["ticker"] for row in result["results"] if row["matched"]]
    assert matched == ["POOL"]
    assert result["metrics_without_data"] == []


def test_metric_coverage_lists_context_metrics_with_data(db):
    pool = _company(db, "POOL")
    _thesis(db, pool, "draft")
    coverage = ScreenerService().metric_coverage(db)
    assert "tiene_tesis" in coverage
    assert "nivel_dca" not in coverage  # sin tabla DCA, no se ofrece
    assert set(CONTEXT_METRICS) >= {"margen_seguridad", "tiene_tesis", "tesis_publicada", "nivel_dca"}


def _real_dca_row(
    *, tenant, symbol, level, company_id=None, status="forming", period="2026-10", day=None, close="100"
):
    """Fila del modelo real (#2310): la tabla ya la crea Base.metadata."""
    from datetime import date as _d
    from decimal import Decimal as _D

    from app.models.entities import DcaSignalState

    return DcaSignalState(
        tenant_id=tenant,
        symbol=symbol,
        company_id=company_id,
        level=level,
        status=status,
        period=period,
        signal_date=day or _d(2026, 10, 24),
        close=_D(close),
        currency="USD",
        metrics={},
        level_prices={},
        sources=[],
        params_version="nico-v1",
        data_source="test",
    )


def _drop_dca_table(db) -> None:
    """Simula «motor DCA no desplegado»: sin la tabla real."""
    from app.models.entities import DcaSignalState

    DcaSignalState.__table__.drop(db.get_bind())


@pytest.mark.parametrize("convention", [None, "valuation-engines-v2", "future_formula"])
def test_unknown_margin_cannot_pass_screener_as_current(db, convention):
    company = _company(db, "UNKNOWN")
    _valuation(db, company, version=1, status="final", mos=0.3)
    _valuation(db, company, version=2, status="final", mos=0.8, convention=convention)
    assert company.id not in context_observations(db, {"margen_seguridad"})
    # History remains untouched, and no fallback to the older verified version.
    latest = db.scalar(sa.select(ValuationOutput).order_by(ValuationOutput.id.desc()))
    assert latest.output_payload["margin_of_safety"] == 0.8


def test_margin_of_safety_sin_n1_por_empresa(db):
    """Perf: el margen de seguridad no hace 1 consulta por empresa valorada.

    Antes: 1 (modelos) + 1 por empresa candidata (60 empresas = 61). Ahora:
    1 (modelos) + consultas IN acotadas para los outputs (60 empresas = 2).
    Salida identica: mismo ORDER BY de modelos, misma agrupacion por modelo y
    misma logica de payload."""
    from sqlalchemy import event

    empresas = [_company(db, f"MOS{i:02d}") for i in range(60)]
    for i, company in enumerate(empresas):
        _valuation(db, company, version=1, status="final", mos=round(0.01 * (i + 1), 2))
    engine = db.get_bind()
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def _cuenta(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    obs = context_observations(db, {"margen_seguridad"})
    event.remove(engine, "before_cursor_execute", _cuenta)
    assert len(obs) == 60
    assert obs[empresas[7].id]["margen_seguridad"].value == Decimal("0.08")
    assert len(statements) <= 4, f"{len(statements)} consultas (N+1 por empresa)"
