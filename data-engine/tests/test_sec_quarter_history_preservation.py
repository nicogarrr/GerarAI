"""La historia trimestral SEC verificada no se pierde al correr la ventana de 12
trimestres en un refresh (los FY ya se preservaban, F353). Datos sinteticos."""
import asyncio
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService


def _q_entries(year_start, n_quarters):
    """Revenues trimestrales (~90 dias) para n trimestres desde year_start Q1."""
    entries = []
    qs = [(1, 1, 3, 31, "Q1"), (4, 1, 6, 30, "Q2"), (7, 1, 9, 30, "Q3"), (10, 1, 12, 31, "Q4")]
    accn_seq = 0
    for i in range(n_quarters):
        year = year_start + i // 4
        sm, sd, em, ed, fp = qs[i % 4]
        accn_seq += 1
        entries.append({
            "start": f"{year}-{sm:02d}-{sd:02d}", "end": f"{year}-{em:02d}-{ed:02d}",
            "val": 1000 + i, "form": "10-Q", "fp": fp,
            "filed": f"{year}-{min(em+1,12):02d}-15",
            "accn": f"0000000001-{i:06d}",
        })
    return entries


def _payload(n_quarters, drop=(), val_shift=0):
    return {
        "cik": 320193, "entityName": "Synthetic Corp",
        "facts": {"us-gaap": {"Revenues": {"units": {"USD": [e for i, e in enumerate(_q_entries(2015, n_quarters)) if i not in drop]}}}},
    }


class FakeSEC:
    def __init__(self, n, drop=()):
        self.n = n
        self.drop = drop
    async def cik_for_ticker(self, ticker): return "0000320193"
    async def company_facts(self, cik): return _payload(self.n, self.drop)
    async def annual_report_anchors(self, cik): return {}
    async def index_accessions(self, cik): return {f"0000000001-{i:06d}" for i in range(self.n)}


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    s = factory()
    s.info["tenant_id"] = "tenant-test"
    return s


def _company(db):
    c = Company(ticker="SYN", name="Synthetic Corp", exchange="NYSE", currency="USD",
                sector="S", industry="I", company_type="operating",
                valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[])
    db.add(c); db.flush()
    return c


def _rows(db):
    return list(db.scalars(select(FinancialFact).where(FinancialFact.metric == "revenue")))


def _refresh(db, company, monkeypatch, n, drop=()):
    svc = FinancialIngestionService()
    monkeypatch.setattr(ingestion, "SECClient", lambda: FakeSEC(n, drop))
    monkeypatch.setattr(ingestion, "sync_company_fact_chunks", lambda db, company: None)
    asyncio.run(svc.refresh_from_sec(db, company))


def test_older_quarters_survive_refresh_with_provenance(monkeypatch):
    db = _session()
    company = _company(db)
    _refresh(db, company, monkeypatch, 16)
    first = {f.period: f for f in _rows(db)}
    assert len(first) == 12  # cap de 12 trimestres por import
    old = {p: (f.value, f.accession_number, f.filed) for p, f in first.items()}
    _refresh(db, company, monkeypatch, 20)  # la ventana corre 4 trimestres
    second = {f.period: f for f in _rows(db)}
    assert set(first) <= set(second), "se perdieron trimestres ya verificados"
    assert len(second) == 16  # 12 antiguos + 4 nuevos, sin duplicar
    assert len(_rows(db)) == len(second)
    # los trimestres que salieron de la ventana conservan valor y proveniencia
    for period in set(first) - {f.period for f in _rows(db) if f.period >= "2017"}:
        f = second[period]
        assert (f.value, f.accession_number, f.filed) == old[period]
        assert f.source_type == "SEC" and f.is_reported is True and f.fiscal_quarter


def test_refresh_is_idempotent_after_restore(monkeypatch):
    db = _session()
    company = _company(db)
    _refresh(db, company, monkeypatch, 16)
    _refresh(db, company, monkeypatch, 20)
    snap = sorted((f.period, f.value) for f in _rows(db))
    _refresh(db, company, monkeypatch, 20)
    assert sorted((f.period, f.value) for f in _rows(db)) == snap


def test_quarter_inside_window_not_returned_is_not_resurrected(monkeypatch):
    """Control negativo: lo que cae DENTRO de la ventana y el import ya no
    devuelve se borra como antes (no se resucita un dato retirado)."""
    db = _session()
    company = _company(db)
    _refresh(db, company, monkeypatch, 16)
    assert any(f.period == "2018-06-30:Q2" for f in _rows(db))
    # indice 14 = 2018 Q3 (2015 + 14//4=3 -> 2018, trimestre 14%4=2 -> Q3)
    dropped = next(f.period for f in _rows(db) if f.period.startswith("2018-09-30"))
    _refresh(db, company, monkeypatch, 16, drop=(14,))
    assert dropped not in {f.period for f in _rows(db)}


def test_other_document_and_unanchored_rows_not_restored(monkeypatch):
    db = _session()
    company = _company(db)
    _refresh(db, company, monkeypatch, 16)
    # derivada sin accession (p.ej. fcf) del mismo documento, trimestre antiguo
    doc_id = _rows(db)[0].source_id
    db.add(FinancialFact(company_id=company.id, metric="fcf_margin", value=Decimal("0.1"),
                         unit="ratio", period="2016-03-31:Q1", fiscal_quarter="Q1",
                         source_id=doc_id, source_type="SEC", is_reported=False))
    db.flush()
    _refresh(db, company, monkeypatch, 20)
    stale = list(db.scalars(select(FinancialFact).where(
        FinancialFact.metric == "fcf_margin", FinancialFact.period == "2016-03-31:Q1")))
    assert stale == []
