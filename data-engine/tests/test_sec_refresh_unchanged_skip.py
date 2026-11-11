"""Refresh SEC sin cambios: huella del payload + version de reglas.

Un segundo ``refresh_from_sec`` con el MISMO payload y las MISMAS reglas
recomputaba y reescribia todo: medido con companyfacts reales
(CHTR/TSLA/MSFT, 5-nov-2026) eran ~800 sentencias por empresa (765 INSERT
identicos en CHTR) y ~21-33k entradas XBRL reescaneadas, aunque ningun
dato hubiera cambiado. Con la huella en el Document la segunda pasada se
omite la recoleccion y escrituras; anclas e indice se verifican siempre.

Reglas que fijan estos tests:
- payload identico + misma version de reglas -> status "unchanged", 0
  INSERT/DELETE en financial_facts, ids estables;
- payload que cambia (un FY nuevo) -> reingesta completa;
- bump de SEC_INGESTION_RULES_VERSION -> reingesta aunque el payload sea
  identico (una regla nueva tiene que alcanzar a quien no cambia);
- un corte as_of NUNCA salta (su resultado es un recorte deliberado) y
  ADEMAS invalida la huella guardada: el siguiente refresh completo
  reingiere, no se fia del estado recortado.
"""

import asyncio
from datetime import date

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import FinancialIngestionService


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session, engine


def _company(db, ticker="MINI"):
    company = Company(
        ticker=ticker, name=ticker, exchange="NMS", currency="USD",
        sector="Communication Services", industry="Telecom Services",
        company_type="standard", valuation_model="standard_dcf",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _fy(year, val, filed):
    return {
        "fy": year, "fp": "FY", "form": "10-K",
        "start": f"{year}-01-01", "end": f"{year}-12-31",
        "val": val, "filed": filed,
    }


def _annotate_anchors(payload):
    """Accn por 10-K y anclas {accn: cierre} sobre EL MISMO objeto payload
    (patron de test_sec_cash_fallback._anchor_fake)."""
    anchors = {}
    for concept in payload["facts"]["us-gaap"].values():
        for entries in concept["units"].values():
            for e in entries:
                if not str(e.get("form", "")).startswith(("10-K", "20-F")):
                    continue
                accn = f"K{e.get('fy')}-{e.get('filed')}"
                e["accn"] = accn
                if str(e.get("end") or "")[5:7] == "12":
                    anchors[accn] = e["end"]
    return anchors


class _FakeSECMini:
    """Payload pequeno y mutable: la bandera de clase ``incluir_fy2026``
    simula que el emisor publica un 10-K nuevo entre dos refresh. Los
    contadores de llamadas miden el fetch evitado sin usar reloj."""

    incluir_fy2026 = False
    _payload = None
    _anchors = None
    llamadas = None

    async def cik_for_ticker(self, ticker, entity_name=None):
        return "0001234567"

    async def company_facts(self, cik):
        cls = type(self)
        cls._registro("company_facts")
        if cls._payload is None:
            assets = [
                _fy(2024, 150000000000, "2025-01-31"),
                _fy(2025, 151000000000, "2026-01-30"),
            ]
            if cls.incluir_fy2026:
                assets.append(_fy(2026, 152000000000, "2027-01-29"))
            cls._payload = {
                "cik": 1234567,
                "entityName": "MINI",
                "facts": {
                    "us-gaap": {
                        "Assets": {"units": {"USD": assets}},
                        "Revenues": {"units": {"USD": [
                            _fy(2024, 54000000000, "2025-01-31"),
                            _fy(2025, 55000000000, "2026-01-30"),
                            {"fy": 2026, "fp": "Q1", "form": "10-Q",
                             "start": "2026-01-01", "end": "2026-03-31",
                             "val": 14000000000, "filed": "2026-04-24"},
                        ]}},
                    }
                },
            }
            cls._anchors = _annotate_anchors(cls._payload)
        return cls._payload

    async def annual_report_anchors(self, cik):
        type(self)._registro("anchors")
        await self.company_facts(cik)
        return type(self)._anchors

    async def index_accessions(self, cik):
        type(self)._registro("index")
        return set(type(self)._anchors)

    @classmethod
    def _registro(cls, nombre):
        if cls.llamadas is None:
            cls.llamadas = {"company_facts": 0, "anchors": 0, "index": 0}
        cls.llamadas[nombre] += 1

    @classmethod
    def reset(cls, *, incluir_fy2026=False):
        cls.incluir_fy2026 = incluir_fy2026
        cls._payload = None
        cls._anchors = None
        cls.llamadas = {"company_facts": 0, "anchors": 0, "index": 0}


def _refresh(db, company, **kwargs):
    service = FinancialIngestionService()
    return asyncio.run(service.refresh_from_sec(db=db, company=company, **kwargs))


def _contar_escrituras_hechos(engine):
    """Contador de INSERT/DELETE sobre financial_facts (sin reloj)."""
    cuenta = {"insert": 0, "delete": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def contar(conn, cursor, statement, parameters, context, executemany):
        s = " ".join(statement.split()).upper()
        if s.startswith("INSERT INTO FINANCIAL_FACTS"):
            cuenta["insert"] += 1
        elif s.startswith("DELETE FROM FINANCIAL_FACTS"):
            cuenta["delete"] += 1

    return cuenta


def _fact_ids(db, company):
    return sorted(
        db.scalars(
            select(FinancialFact.id).where(FinancialFact.company_id == company.id)
        ).all()
    )


def test_segunda_pasada_identica_no_reescribe_ni_reescanea(db_engine, monkeypatch):
    _FakeSECMini.reset()
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECMini)
    db, engine = db_engine
    company = _company(db)

    first = _refresh(db, company)
    assert first["status"] == "ingested"
    assert first["facts_imported"] > 0
    ids_antes = _fact_ids(db, company)

    cuenta = _contar_escrituras_hechos(engine)
    second = _refresh(db, company)

    assert second["status"] == "unchanged"
    assert second["facts_imported"] == 0
    assert second["unchanged"] is True
    # CERO escrituras de hechos; anclas/indice siguen comprobando procedencia:
    assert cuenta == {"insert": 0, "delete": 0}
    assert _FakeSECMini.llamadas["anchors"] == 2  # verificar cambios de calendario
    assert _FakeSECMini.llamadas["index"] == 2
    assert _fact_ids(db, company) == ids_antes     # mismas filas, mismo id


def test_payload_con_filing_nuevo_reingiere(db_engine, monkeypatch):
    _FakeSECMini.reset()
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECMini)
    db, engine = db_engine
    company = _company(db)
    _refresh(db, company)

    _FakeSECMini.reset(incluir_fy2026=True)  # el emisor publica el 10-K de FY2026
    third = _refresh(db, company)

    assert third["status"] == "ingested"
    years = {
        f.fiscal_year
        for f in db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == "total_assets",
            )
        )
    }
    assert 2026 in years


def test_bump_de_version_de_reglas_reingiere_con_el_mismo_payload(db_engine, monkeypatch):
    _FakeSECMini.reset()
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECMini)
    db, engine = db_engine
    company = _company(db)
    _refresh(db, company)

    monkeypatch.setattr(ingestion, "SEC_INGESTION_RULES_VERSION", 999)
    rerun = _refresh(db, company)
    assert rerun["status"] == "ingested"
    assert rerun["facts_imported"] > 0


def test_as_of_nunca_salta_e_invalida_la_huella(db_engine, monkeypatch):
    _FakeSECMini.reset()
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECMini)
    db, engine = db_engine
    company = _company(db)
    _refresh(db, company)

    # Corte de informacion a mitad de historia: corre completo pese a que el
    # payload es identico...
    as_of_run = _refresh(db, company, as_of=date(2025, 6, 30))
    assert as_of_run["status"] == "ingested"
    assert as_of_run["date_filter_applied"] is True

    # ...y como deja un recorte en disco, invalida la huella: el siguiente
    # refresh completo tiene que reingerir, no saltar.
    after = _refresh(db, company)
    assert after["status"] == "ingested"


@pytest.mark.parametrize("mirror_method", ["company_facts", "annual_report_anchors", "index_accessions"])
def test_identical_mirror_payload_does_not_skip_or_keep_direct_fingerprint(
    db_engine, monkeypatch, mirror_method,
):
    from app.models.entities import Document
    from app.services.connectors import sec_edgar

    _FakeSECMini.reset()
    monkeypatch.setattr(ingestion, "SECClient", _FakeSECMini)
    db, _ = db_engine
    company = _company(db)
    first = _refresh(db, company)
    document = db.get(Document, first["source_document_id"])
    assert document.metadata_["sec_payload_fingerprint"]
    assert document.metadata_["sec_anchor_fingerprint"]
    before = sorted(
        (row.metric, row.period, row.value, row.unit)
        for row in db.scalars(select(FinancialFact))
    )
    original = getattr(_FakeSECMini, mirror_method)

    async def served_by_mirror(self, cik):
        result = await original(self, cik)
        sec_edgar._record_mirror_serve({"synced_at": "2026-11-05T10:00:00Z"})
        return result

    monkeypatch.setattr(_FakeSECMini, mirror_method, served_by_mirror)
    second = _refresh(db, company)
    assert second["status"] == "ingested"
    assert second["mirror"]["documents"] >= 1
    assert second["mirror"]["synced_at"] == "2026-11-05T10:00:00Z"
    assert document.metadata_["mirror"] == second["mirror"]
    assert "sec_payload_fingerprint" not in document.metadata_
    assert "sec_anchor_fingerprint" not in document.metadata_
    assert sorted(
        (row.metric, row.period, row.value, row.unit)
        for row in db.scalars(select(FinancialFact))
    ) == before
    monkeypatch.setattr(_FakeSECMini, mirror_method, original)
    assert _refresh(db, company)["status"] == "ingested"
    assert document.metadata_["mirror"] is None
    assert _refresh(db, company)["status"] == "unchanged"
