"""Tenant-private inferences with coherent pre-revenue valuation and provenance."""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base as CoreBase  # noqa: F401  (registra listeners)
from app.models.entities import Base, Company, InferredInput, TenantOwnedMixin
from app.services.inferred_input_service import InferredInputService
from app.valuation.engines.base import ValuationContext
from app.valuation.engines.pre_revenue import PreRevenueScenarioEngine

BASE = "Dado el margen FCF historico de Iridium 2021-2025 con fuentes SEC, inferimos 0,25"
URLS = ["https://www.sec.gov/Archives/edgar/data/1780312/x.htm"]


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


class _Snap:
    # FinancialSnapshot.excluded_present (928a2cec): los motores lo leen siempre.
    excluded_present: list = []
    coherent = True
    as_of_period = "2026-06-30:Q2"
    income_statement = None
    balance_sheet = None
    shares_period = None
    warnings: list = []
    facts: dict = {"revenue": type("F", (), {"confidence": 0.9})()}
    missing_inputs: list = []

    def __init__(self, values):
        self._v = values

    def value(self, metric):
        return self._v.get(metric)

    def fact_ids(self):
        return {}

    def periods(self):
        return {}


VALUES = {"revenue": 70_918_000.0, "shares_diluted": 255_982_592.0, "operating_cash_flow": -71_517_000.0, "net_debt": 675_169_000.0}


def _company(db):
    db.info.setdefault("tenant_id", 2)
    c = Company(ticker="CUV", name="Cov", exchange="NASDAQ", company_type="growth",
                valuation_model="pre_revenue", factor_tags=["pre_fcf"])
    db.add(c)
    db.commit()
    return c


def _value(db, company, values=None):
    ctx = ValuationContext(db=db, company=company, snapshot=_Snap(values or VALUES),
                           current_price=58.0, engine_key="pre_revenue")
    return PreRevenueScenarioEngine().value(ctx)


def test_inferred_input_is_tenant_owned():
    assert issubclass(InferredInput, TenantOwnedMixin)


def test_inferred_input_invisible_from_other_tenant_sessions(engine):
    with Session(engine) as writer:
        writer.info["tenant_id"] = 2
        company = _company(writer)
        row = InferredInputService().create(
            writer, company, input_key="fcf_margin", value=Decimal("0.25"), base=BASE, source_urls=URLS
        )
        assert row.tenant_id == 2
        company_id = company.id
    for tenant in (1, 5, 6, None):
        with Session(engine) as reader:
            if tenant is not None:
                reader.info["tenant_id"] = tenant
            got = InferredInputService().latest_valid(reader, company_id, "fcf_margin")
            assert got is None


def test_coherent_branch_without_fcf_or_inferred_stays_insufficient(engine):
    with Session(engine) as db:
        company = _company(db)
        result = _value(db, company)
        assert result["status"] == "insufficient_data"
        assert "normalized_fcf_or_fcf_margin" in result["missing_inputs"]


def test_coherent_branch_consults_inferred_margin_and_is_not_publishable(engine):
    with Session(engine) as db:
        db.info["tenant_id"] = 2
        company = _company(db)
        InferredInputService().create(
            db, company, input_key="fcf_margin", value=Decimal("0.25"), base=BASE, source_urls=URLS
        )
    with Session(engine) as other:
        other.info["tenant_id"] = 2
        company = other.scalar(select(Company).where(Company.ticker == "CUV"))
        result = _value(other, company)
        assert result["status"] == "partial"
        assert result["publishable"] is False
        (inferred,) = result["trace"]["inferred_inputs"]
        assert inferred["origen"] == "INFERIDO" and inferred["urls_inferencia"] == URLS
        assert inferred["input_key"] == "fcf_margin" and inferred["inferred_input_id"]
        assert result["base_value"] is not None


def test_coherent_branch_ignores_invalid_inferred_input(engine):
    with Session(engine) as db:
        company = _company(db)
        db.add(InferredInput(company_id=company.id, input_key="fcf_margin", value=Decimal("0.25"),
                             base="corta", source_urls=[]))
        db.commit()
        result = _value(db, company)
        assert result["status"] == "insufficient_data"


def test_reported_fcf_wins_over_inferred(engine):
    with Session(engine) as db:
        company = _company(db)
        InferredInputService().create(
            db, company, input_key="fcf_margin", value=Decimal("0.25"), base=BASE, source_urls=URLS
        )
        values = dict(VALUES, free_cash_flow=-80_000_000.0)
        result = _value(db, company, values)
        # El FCF reportado (negativo) gana: el inferido nunca lo sustituye
        # como dato. Con convergencia de margen el reportado es el PUNTO DE
        # PARTIDA (hecho medido) y el inferido solo fija la madurez; la
        # orientacion queda bloqueada y nunca se publica cifra negativa.
        assert result["publishable"] is False
        for key in ("bear_value", "base_value", "bull_value", "expected_value"):
            value = result[key]
            assert value is None or value > 0
        if result["status"] == "insufficient_data":
            assert result.get("trace", {}).get("inferred_inputs", []) == []
        else:
            assert "inferred_fcf_margin_target" in result["publication_blockers"]
            assert result["trace"]["reported_fcf_margin"] == pytest.approx(
                -80_000_000.0 / 70_918_000.0
            )


def test_inputs_facts_and_documents_all_stay_isolated(engine):
    from app.models.entities import Document, FinancialFact

    with Session(engine) as t2:
        t2.info["tenant_id"] = 2
        company = _company(t2)
        InferredInputService().create(
            t2, company, input_key="fcf_margin", value=Decimal("0.25"), base=BASE, source_urls=URLS
        )
        t2.add(Document(company_id=company.id, title="opinion privada", source_type="user_opinion",
                        source_url="https://example.com/x"))
        t2.add(FinancialFact(company_id=company.id, metric="revenue", value=Decimal("1"),
                             period="2026-06-30:Q2", source_type="SEC"))
        t2.commit()
        cid = company.id
    with Session(engine) as t5:
        t5.info["tenant_id"] = 5
        assert InferredInputService().latest_valid(t5, cid, "fcf_margin") is None
        assert t5.scalars(select(Document).where(Document.company_id == cid)).all() == []
        assert t5.scalars(select(FinancialFact).where(FinancialFact.company_id == cid)).all() == []
    with Session(engine) as t2b:
        t2b.info["tenant_id"] = 2
        assert len(t2b.scalars(select(Document).where(Document.company_id == cid)).all()) == 1


@pytest.mark.parametrize("coherent", [True, False])
@pytest.mark.parametrize("reported", [
    {"fcf_margin": -0.6, "free_cash_flow": -80_000_000.0},
    {"fcf_margin": 0.0, "free_cash_flow": 0.0},
    {"free_cash_flow": -80_000_000.0},
    {"free_cash_flow": 0.0},
    {"fcf_margin": -0.6},
    {"fcf_margin": 0.0},
    {"fcf_margin": 0.25, "free_cash_flow": -80_000_000.0},
])
def test_reported_non_positive_fcf_blocks_both_paths(engine, coherent, reported):
    with Session(engine) as db:
        company = _company(db)
        InferredInputService().create(
            db, company, input_key="fcf_margin", value=Decimal("0.25"),
            base=BASE, source_urls=URLS,
        )
        snapshot = _Snap(dict(VALUES, **reported))
        snapshot.coherent = coherent
        context = ValuationContext(
            db=db, company=company, snapshot=snapshot,
            current_price=58.0, engine_key="pre_revenue",
        )
        result = PreRevenueScenarioEngine().value(context)
        # Contrato (30-oct-2026): el margen reportado NO positivo nunca se
        # proyecta como dato. Con un objetivo de madurez inferido y validado
        # puede ofrecerse una ORIENTACIÓN por convergencia de margen — el
        # margen reportado sigue siendo el punto de partida (hecho medido) y
        # el resultado queda bloqueado para publicación; si la convergencia
        # no da escenarios positivos (p. ej. deuda neta enorme), se mantiene
        # el N/D explicado. En ningún caso se publica una cifra negativa.
        assert result["publishable"] is False
        for key in ("bear_value", "base_value", "bull_value", "expected_value"):
            value = result[key]
            assert value is None or value > 0
        if result["status"] == "insufficient_data":
            assert "non_negative_fcf_margin" in result["missing_inputs"]
            assert result.get("trace", {}).get("inferred_inputs", []) == []
        else:
            assert "inferred_fcf_margin_target" in result["publication_blockers"]
            assert result["trace"]["method"] == "fcff_dcf_margin_convergence"
