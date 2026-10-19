"""Deuda neta derivada cuando el emisor ya no reporta deuda financiera.

Caso medido en prod (EXEL, 19/10/2026): pago su deuda y desde FY2017 no
reporta ningun concepto LongTermDebt*/Debt*; con la regla anterior la deuda
neta moria en FY2017 y la tesis pedia "Deuda neta" aunque el 10-K FY2025
tiene el balance completo. Criterio decidido por el coordinador (pendiente de confirmacion de Nico): sin concepto de deuda pero con
balance completo (caja + activos + pasivos del mismo ejercicio), deuda neta =
-caja, is_reported=False, con etiqueta "ausencia de concepto, no un cero
reportado" en document.metadata_. Sin balance completo: N/D (sin fila).

La fixture replica el calendario 52/53 semanas de EXEL (cierres el primer
viernes de enero; FY2024 con span de 371 dias), que es ademas la guarda de
regresion del hueco de capex FY2024/FY2025 medido en prod.
"""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker="EXEL"):
    company = Company(
        ticker=ticker,
        name=ticker,
        exchange="NASDAQ",
        currency="USD",
        sector="S",
        industry="I",
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


# Cierres 52/53 semanas estilo EXEL: (end, start o None)
YEARS = [
    ("2023-12-29", "2022-12-31"),  # 363 d
    ("2025-01-03", "2023-12-30"),  # 371 d (semana 53): el hueco de prod
    ("2026-01-02", "2025-01-04"),  # 363 d
]
ACCNS = {"2023-12-29": "K23", "2025-01-03": "K24", "2026-01-02": "K25"}
FILED = {"2023-12-29": "2024-02-06", "2025-01-03": "2025-02-11", "2026-01-02": "2026-02-10"}


def _flow(concept_vals, unit="USD"):
    """{concept: {units: {USD: [entries 10-K FY]}}} para hechos de flujo."""
    out = {}
    for concept, vals in concept_vals.items():
        entries = []
        for (end, start), val in zip(YEARS, vals):
            entries.append(
                {
                    "fy": int(end[:4]),
                    "fp": "FY",
                    "form": "10-K",
                    "start": start,
                    "end": end,
                    "val": val,
                    "filed": FILED[end],
                    "accn": ACCNS[end],
                }
            )
        out[concept] = {"units": {unit: entries}}
    return out


def _instant(concept_vals, unit="USD"):
    out = {}
    for concept, vals in concept_vals.items():
        entries = []
        for (end, _start), val in zip(YEARS, vals):
            entries.append(
                {
                    "fy": int(end[:4]),
                    "fp": "FY",
                    "form": "10-K",
                    "end": end,
                    "val": val,
                    "filed": FILED[end],
                    "accn": ACCNS[end],
                }
            )
        out[concept] = {"units": {unit: entries}}
    return out


def _payload(*, with_debt_zero=False, with_balance=True, debt_signals=()):
    """debt_signals: entradas extra de tags de deuda (pasivo) para la regla de
    evidencia positiva. Cada tupla es (concept, end, val); se les da un accn
    sin ancla para que NO entren como hechos (EXEL: su deuda vieja no se
    re-ingiere) pero sigan visibles para el escaneo bruto de señal."""
    us_gaap = {}
    us_gaap.update(
        _flow(
            {
                "RevenueFromContractWithCustomerExcludingAssessedTax": [1000, 2000, 3000],
                "NetCashProvidedByUsedInOperatingActivities": [100, 200, 300],
                "PaymentsToAcquirePropertyPlantAndEquipment": [10, 20, 30],
            }
        )
    )
    us_gaap.update(
        _instant(
            {
                "CashAndCashEquivalentsAtCarryingValue": [500, 600, 700],
            }
        )
    )
    if with_balance:
        us_gaap.update(
            _instant(
                {
                    "Assets": [5000, 6000, 7000],
                    "Liabilities": [2000, 2500, 3000],
                }
            )
        )
    if with_debt_zero:
        us_gaap.update(_instant({"LongTermDebt": [0, 0, 0]}))
    for concept, end, val in debt_signals:
        us_gaap.setdefault(concept, {"units": {"USD": []}})["units"]["USD"].append(
            {
                "fy": int(end[:4]),
                "fp": "FY",
                "form": "10-K",
                "end": end,
                "val": val,
                "filed": end[:4] + "-03-01",
                "accn": f"KOLD-{concept}-{end}",
            }
        )
    # Decoys que NO deben entrar: TTM de ~2 anos y fin de mes distinto del
    # cierre declarado en portada, ambos dentro del 10-K FY2025.
    us_gaap["PaymentsToAcquirePropertyPlantAndEquipment"]["units"]["USD"].extend(
        [
            {
                "fy": 2025,
                "fp": "FY",
                "form": "10-K",
                "start": "2023-12-30",
                "end": "2026-01-02",
                "val": 999,
                "filed": "2026-02-10",
                "accn": "K25",
            },
            {
                "fy": 2025,
                "fp": "FY",
                "form": "10-K",
                "start": "2024-07-01",
                "end": "2025-06-30",
                "val": 888,
                "filed": "2026-02-10",
                "accn": "K25",
            },
        ]
    )
    return {"facts": {"us-gaap": us_gaap}}


class _FakeSEC:
    def __init__(self, payload):
        self._payload = payload

    async def cik_for_ticker(self, ticker):
        return "0000939767"

    async def company_facts(self, cik):
        return self._payload

    async def annual_report_anchors(self, cik):
        return {accn: end for end, accn in ACCNS.items()}


def _run(db, monkeypatch, payload):
    monkeypatch.setattr(ingestion, "SECClient", lambda: _FakeSEC(payload))
    company = _company(db)
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    return company


def _facts(db, company, metric):
    return list(
        db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == metric,
                FinancialFact.fiscal_quarter == "FY",
            )
        )
    )


def _document(db, company):
    return db.scalar(select(Document).where(Document.company_id == company.id, Document.source_type == "SEC"))


def test_capex_52_53_week_y_fcf_derivado(db, monkeypatch):
    """Guarda de regresion del hueco de prod: el capex de FY2024 (span 371 d,
    cierre 2025-01-03) y FY2025 entra; FCF = CFO - capex se deriva por ano."""
    company = _run(db, monkeypatch, _payload())
    capex = {f.period: f for f in _facts(db, company, "capital_expenditure")}
    assert set(capex) == {"2023-12-29:FY", "2025-01-03:FY", "2026-01-02:FY"}
    assert capex["2025-01-03:FY"].value == Decimal("-20")  # signo gasto
    fcf = {f.period: f for f in _facts(db, company, "free_cash_flow")}
    assert fcf["2025-01-03:FY"].value == Decimal("180")  # 200 - 20
    assert fcf["2026-01-02:FY"].value == Decimal("270")  # 300 - 30
    assert all(f.is_reported is False for f in fcf.values())


def test_net_debt_sin_concepto_de_deuda_es_menos_caja_etiquetada(db, monkeypatch):
    company = _run(db, monkeypatch, _payload())
    net_debt = {f.period: f for f in _facts(db, company, "net_debt")}
    assert set(net_debt) == {"2023-12-29:FY", "2025-01-03:FY", "2026-01-02:FY"}
    assert net_debt["2026-01-02:FY"].value == Decimal("-700")  # -caja
    assert all(f.is_reported is False for f in net_debt.values())
    note = (_document(db, company).metadata_ or {}).get("net_debt_no_financial_debt_periods")
    assert set(note) == set(net_debt)
    assert "ausencia de concepto, no un cero reportado" in note["2026-01-02:FY"]
    assert "sin deuda financiera reportada" in note["2026-01-02:FY"]


def test_deuda_reportada_cero_usa_la_via_normal_sin_etiqueta(db, monkeypatch):
    """Contraejemplo: un cero REPORTADO (LongTermDebt=0) no es ausencia de
    concepto: net_debt = deuda - caja por la via normal, sin nota."""
    company = _run(db, monkeypatch, _payload(with_debt_zero=True))
    net_debt = {f.period: f for f in _facts(db, company, "net_debt")}
    assert net_debt["2026-01-02:FY"].value == Decimal("-700")  # 0 - 700
    assert net_debt["2026-01-02:FY"].confidence == Decimal("0.85")
    document = _document(db, company)
    assert "net_debt_no_financial_debt_periods" not in (document.metadata_ or {})


def test_sin_balance_completo_no_hay_inferencia(db, monkeypatch):
    """Sin activos/pasivos del mismo ejercicio la ausencia de deuda no es
    probatoria: no se crea fila (N/D), como manda el criterio decidido por el coordinador."""
    company = _run(db, monkeypatch, _payload(with_balance=False))
    assert _facts(db, company, "net_debt") == []
    document = _document(db, company)
    assert "net_debt_no_financial_debt_periods" not in (document.metadata_ or {})


def test_deuda_en_tag_no_mapeado_reciente_da_nd(db, monkeypatch):
    """Regla del auditor: ShortTermBorrowings (fuera del alcance de
    total_debt) con valor reciente prueba que la ausencia de total_debt es un
    hueco de mapeo, no "sin deuda": deuda neta N/D, sin fila ni etiqueta."""
    payload = _payload(debt_signals=[("ShortTermBorrowings", "2025-01-03", 9000)])
    company = _run(db, monkeypatch, payload)
    assert _facts(db, company, "net_debt") == []
    document = _document(db, company)
    assert "net_debt_no_financial_debt_periods" not in (document.metadata_ or {})


def test_senales_de_deuda_antiguas_no_bloquean(db, monkeypatch):
    """EXEL real: LongTermDebt FY2017 (=0), FinanceLeaseLiability 2019-09-27 y
    RepaymentsOfLongTermDebt 2020-01-03 son los ultimos rastros de deuda; a
    mas de 5 anos del ejercicio mas reciente (2026-01-02) la inferencia
    "sin deuda financiera reportada" se mantiene."""
    payload = _payload(
        debt_signals=[
            ("LongTermDebt", "2017-12-29", 0),
            ("FinanceLeaseLiabilityCurrent", "2019-09-27", 1200),
            ("RepaymentsOfLongTermDebt", "2020-01-03", 400000),
        ]
    )
    company = _run(db, monkeypatch, payload)
    net_debt = {f.period: f for f in _facts(db, company, "net_debt")}
    assert set(net_debt) == {"2023-12-29:FY", "2025-01-03:FY", "2026-01-02:FY"}
    assert net_debt["2026-01-02:FY"].value == Decimal("-700")


def test_claim_de_tesis_lleva_el_matiz_visible(db, monkeypatch):
    """La UI no lee metadata_ del documento: el matiz viaja en el claim."""
    from app.services.thesis_service import ThesisService

    company = _run(db, monkeypatch, _payload())
    fact = next(f for f in _facts(db, company, "net_debt") if f.period == "2026-01-02:FY")
    claims = ThesisService()._build_claims(company, {"net_debt": fact}, {"status": "partial"})
    claim = next(c for c in claims if c["predicate"] == "net_debt")
    assert "Calculada; sin deuda financiera reportada." in claim["claim"]
    assert claim["verification_state"] == "derived"
