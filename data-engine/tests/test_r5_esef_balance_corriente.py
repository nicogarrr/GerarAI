"""Balance corriente y reservas en la ingesta ESEF (r5-bugs2, 11-nov-2026).

Antes: ``ESEF_METRIC_MAP`` no leía ``ifrs-full:CurrentAssets``, ``ifrs-full:CurrentLiabilities`` ni
``ifrs-full:RetainedEarnings``, aunque el mapa IFRS de los 20-F/40-F de la SEC (``SEC_IFRS_METRIC_MAP``) sí los
lee. Todo emisor europeo quedaba sin la señal de liquidez de Piotroski y sin Altman Z'' (X1 capital circulante,
X2 reservas), aunque su informe ESEF los etiquete (Intertek FY2025, Eurofins FY2024 en filings.xbrl.org).
"""
import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_health import HealthFact, calculate_health
from app.services.financial_ingestion_service import FinancialIngestionService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _dur(val, start, end, dims=None):
    return {"start": start, "end": end, "val": str(val), "decimals": 0, "lei": "L", "dims": dims or []}


def _inst(val, instant, dims=None):
    return {"instant": instant, "val": str(val), "decimals": 0, "lei": "L", "dims": dims or []}


def _year(y: int, assets, current_assets, current_liabilities, retained, revenue, gross, net, ebt, liabilities,
          equity, ocf):
    s, e = f"{y}-01-01", f"{y}-12-31"
    return {
        "ifrs-full:Assets": _inst(assets, e), "ifrs-full:CurrentAssets": _inst(current_assets, e),
        "ifrs-full:CurrentLiabilities": _inst(current_liabilities, e), "ifrs-full:RetainedEarnings": _inst(retained, e),
        "ifrs-full:Liabilities": _inst(liabilities, e), "ifrs-full:Equity": _inst(equity, e),
        "ifrs-full:Revenue": _dur(revenue, s, e), "ifrs-full:GrossProfit": _dur(gross, s, e),
        "ifrs-full:ProfitLoss": _dur(net, s, e), "ifrs-full:ProfitLossBeforeTax": _dur(ebt, s, e),
        "ifrs-full:CashFlowsFromUsedInOperatingActivities": _dur(ocf, s, e),
        "ifrs-full:FinanceCosts": _dur(30, s, e),
    }


def _snapshot():
    years = [
        _year(2025, 4200, 1800, 1200, 1500, 3400, 1500, 400, 520, 2400, 1800, 600),
        _year(2024, 4000, 1600, 1200, 1300, 3300, 1400, 360, 480, 2300, 1700, 560),
        _year(2023, 3800, 1500, 1150, 1150, 3200, 1350, 330, 440, 2250, 1550, 520),
    ]
    facts: dict = {}
    for year in years:
        for concept, entry in year.items():
            facts.setdefault(concept, {}).setdefault("iso4217:GBP", []).append(entry)
    # Un miembro (dimensión) nunca es el consolidado.
    facts["ifrs-full:CurrentAssets"]["iso4217:GBP"].append(_inst(9, "2025-12-31", dims=["ifrs-full:SegmentsAxis"]))
    return {"lei": "2138003GAT25WW1RN369", "ticker": "ITRK.L", "entity_name": "INTERTEK GROUP PLC",
            "period_end": "2025-12-31", "fxo_id": "fxo-itrk", "fetched_at": "2026-11-11", "facts": facts}


def _ingest(db, monkeypatch):
    monkeypatch.setattr(ingestion.esef_connector, "read_esef_snapshot", lambda ticker: _snapshot())
    company = Company(ticker="ITRK.L", name="Intertek Group plc", exchange="LSE", currency="GBP", sector="Industrials",
                      industry="I", company_type="operating", valuation_model="unassigned", special_sources=[],
                      special_risks=[], factor_tags=[])
    db.add(company)
    db.commit()
    asyncio.run(FinancialIngestionService().refresh_from_esef(db=db, company=company))
    return {(f.metric, f.period): f for f in db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id))}


def test_esef_importa_activo_y_pasivo_corriente_y_reservas(db, monkeypatch):
    by = _ingest(db, monkeypatch)
    for metric, value in (("current_assets", 1800), ("current_liabilities", 1200), ("retained_earnings", 1500)):
        fact = by[(metric, "2025-12-31:FY")]
        assert fact.value == Decimal(value), metric
        assert fact.unit == "GBP" and fact.source_type == "ESEF" and fact.is_reported
    assert by[("current_assets", "2023-12-31:FY")].value == Decimal(1500)


def test_la_regla_nueva_reingiere_snapshots_sin_cambios():
    # Cambia el resultado de reingerir el MISMO snapshot: la versión de reglas ESEF sube (huella del snapshot).
    assert ingestion.ESEF_INGESTION_RULES_VERSION >= 7
    mapped = {metric for metric, _concepts, _unit in ingestion.ESEF_METRIC_MAP}
    assert {"current_assets", "current_liabilities", "retained_earnings"} <= mapped


def test_salud_de_un_emisor_esef_ya_evalua_liquidez_y_altman(db, monkeypatch):
    by = _ingest(db, monkeypatch)
    facts = []
    for (metric, period), f in by.items():
        if f.fiscal_quarter != "FY" or not f.is_reported:
            continue
        end = date.fromisoformat(period.split(":")[0])
        facts.append(HealthFact(f.id, metric, end.year, float(f.value), f.unit, end,
                                "https://filings.xbrl.org/x.json", "ESEF", 1))
    out = calculate_health(facts, sector="Industrials", company_type="operating", today=date(2026, 11, 11))
    liquidity = next(s for s in out["piotroski"]["signals"] if s["id"] == "liquidity")
    assert liquidity["point"] == 1, liquidity
    assert out["altman"]["score"] is not None, out["altman"]
