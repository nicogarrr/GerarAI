"""Hermetic tests: EPS/acciones por clases desde instancias XBRL (Visa, BRK.B).

Sin red. La instancia es un fixture minimo con la estructura real de EDGAR:
contexts con explicitMember de clase + hechos anuales/trimestrales.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, Document, FinancialFact, Tenant
from app.services.class_filer_eps_service import (
    backfill_class_based_eps,
    pick_member,
)
from app.services.connectors.sec_xbrl_instance import (
    parse_instance_dimensioned_facts,
)

INSTANCE_XML = """<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:us-gaap="http://fasb.org/us-gaap/2023"
      xmlns:v="http://www.example.com/v">
  <unit id="uUSD"><divide><unitNumerator><measure>iso4217:USD</measure></unitNumerator><unitDenominator><measure>xbrli:shares</measure></unitDenominator></divide></unit>
  <unit id="ushares"><measure>xbrli:shares</measure></unit>
  <context id="c1"><entity><identifier scheme="s">X</identifier>
    <segment><explicitMember dimension="v:CommonClassAxis">us-gaap:CommonClassAMember</explicitMember></segment></entity>
    <period><startDate>2024-10-01</startDate><endDate>2025-09-30</endDate></period></context>
  <context id="c2"><entity><identifier scheme="s">X</identifier>
    <segment><explicitMember dimension="v:CommonClassAxis">us-gaap:CommonClassAMember</explicitMember></segment></entity>
    <period><startDate>2023-10-01</startDate><endDate>2024-09-30</endDate></period></context>
  <context id="c3"><entity><identifier scheme="s">X</identifier>
    <segment><explicitMember dimension="v:CommonClassAxis">v:CommonClassBMember</explicitMember></segment></entity>
    <period><startDate>2024-10-01</startDate><endDate>2025-09-30</endDate></period></context>
  <context id="c4"><entity><identifier scheme="s">X</identifier>
    <segment><explicitMember dimension="v:CommonClassAxis">us-gaap:CommonClassAMember</explicitMember></segment></entity>
    <period><startDate>2025-04-01</startDate><endDate>2025-06-30</endDate></period></context>
  <context id="c5"><entity><identifier scheme="s">X</identifier></entity>
    <period><startDate>2024-10-01</startDate><endDate>2025-09-30</endDate></period></context>
  <us-gaap:EarningsPerShareDiluted contextRef="c1">10.20</us-gaap:EarningsPerShareDiluted>
  <us-gaap:EarningsPerShareDiluted contextRef="c2">9.73</us-gaap:EarningsPerShareDiluted>
  <us-gaap:EarningsPerShareDiluted contextRef="c3">15.95</us-gaap:EarningsPerShareDiluted>
  <us-gaap:EarningsPerShareDiluted contextRef="c4">2.51</us-gaap:EarningsPerShareDiluted>
  <us-gaap:EarningsPerShareDiluted contextRef="c5">10.20</us-gaap:EarningsPerShareDiluted>
  <us-gaap:EarningsPerShareDiluted contextRef="c1x">NaN</us-gaap:EarningsPerShareDiluted>
  <us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding contextRef="c1">1966000000</us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding>
  <us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding contextRef="c2">2029000000</us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding>
</xbrl>
"""

BRK_INSTANCE_XML = """<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:us-gaap="http://fasb.org/us-gaap/2023"
      xmlns:brka="http://www.example.com/brka">
  <unit id="uUSD"><divide><unitNumerator><measure>iso4217:USD</measure></unitNumerator><unitDenominator><measure>xbrli:shares</measure></unitDenominator></divide></unit>
  <unit id="ushares"><measure>xbrli:shares</measure></unit>
  <context id="a1"><entity><identifier scheme="s">X</identifier>
    <segment><explicitMember dimension="brka:EquivalentClassAxis">brka:EquivalentClassAMember</explicitMember></segment></entity>
    <period><startDate>2025-01-01</startDate><endDate>2025-12-31</endDate></period></context>
  <context id="b1"><entity><identifier scheme="s">X</identifier>
    <segment><explicitMember dimension="brka:EquivalentClassAxis">brka:EquivalentClassBMember</explicitMember></segment></entity>
    <period><startDate>2025-01-01</startDate><endDate>2025-12-31</endDate></period></context>
  <us-gaap:EarningsPerShareBasic contextRef="a1">61900</us-gaap:EarningsPerShareBasic>
  <us-gaap:EarningsPerShareBasic contextRef="b1">41.27</us-gaap:EarningsPerShareBasic>
  <us-gaap:WeightedAverageNumberOfSharesOutstandingBasic contextRef="b1">2157335139</us-gaap:WeightedAverageNumberOfSharesOutstandingBasic>
</xbrl>
"""

SEGMENT_INSTANCE_XML = """<?xml version="1.0"?>
<!-- origin: synthetic_fixture. Un unico hecho dimensionado por SEGMENTO: es
     el BPA de un negocio, no el del emisor, y no puede escribirse como
     eps_diluted del consolidado (FIX5-9). -->
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:us-gaap="http://fasb.org/us-gaap/2023">
  <unit id="uUSD"><divide><unitNumerator><measure>iso4217:USD</measure></unitNumerator><unitDenominator><measure>xbrli:shares</measure></unitDenominator></divide></unit>
  <unit id="ushares"><measure>xbrli:shares</measure></unit>
  <context id="s1"><entity><identifier scheme="s">X</identifier>
    <segment><explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">us-gaap:DomesticMember</explicitMember></segment></entity>
    <period><startDate>2025-01-01</startDate><endDate>2025-12-31</endDate></period></context>
  <us-gaap:EarningsPerShareDiluted contextRef="s1" unitRef="uUSD" decimals="2">1.25</us-gaap:EarningsPerShareDiluted>
</xbrl>
"""


def _parse(xml: str):
    return parse_instance_dimensioned_facts(io.BytesIO(xml.encode()))


def test_parse_keeps_only_dimensioned_annual_facts():
    facts = _parse(INSTANCE_XML)
    eps = [f for f in facts if f.tag == "EarningsPerShareDiluted"]
    # c1, c2 (anuales clase A), c3 (anual clase B1); fuera: c4 (91d), c5 (sin miembro), NaN.
    assert {f.value for f in eps} == {Decimal("10.20"), Decimal("9.73"), Decimal("15.95")}
    assert all(f.members for f in facts)
    assert all(300 <= f.duration_days <= 380 for f in facts)


def test_parse_accepts_53_week_years():
    xml = INSTANCE_XML.replace("2024-09-30", "2024-10-04")  # 369 dias
    facts = _parse(xml)
    assert any(f.value == Decimal("9.73") for f in facts)


def test_pick_member_prefers_configured_then_single_member():
    facts = _parse(INSTANCE_XML)
    assert pick_member(facts, "CommonClassAMember") == "CommonClassAMember"
    assert pick_member(facts, None) is None  # A y B: varias clases, no se elige a ciegas
    single = [f for f in facts if f.member_names == ("CommonClassAMember",)]
    assert pick_member(single, None) == "CommonClassAMember"


def test_parse_propagates_the_axis_of_each_member():
    facts = _parse(INSTANCE_XML)
    pairs = {pair for f in facts for pair in f.members}
    assert ("v:CommonClassAxis", "CommonClassAMember") in pairs
    assert ("v:CommonClassAxis", "CommonClassBMember") in pairs


def test_pick_member_refuses_a_segment_member():
    """Un hecho por SEGMENTO es el BPA de un negocio, no el del emisor: ni el
    eje es de clase ni el miembro es una clase (FIX5-9)."""
    facts = _parse(SEGMENT_INSTANCE_XML)
    assert facts, "el hecho dimensionado del segmento debe parsearse"
    assert pick_member(facts, "CommonClassAMember") is None
    assert pick_member(facts, None) is None


def test_backfill_writes_nothing_for_a_segment_only_instance(db):
    company = _company(db, "ZZZ")
    fetch_json, fetch_bytes = _fake_fetchers(SEGMENT_INSTANCE_XML)
    result = backfill_class_based_eps(
        db, company, cik="1", fetch_json=fetch_json, fetch_bytes=fetch_bytes
    )
    assert result.facts_written == 0
    assert result.member_used is None
    assert result.skipped_reason == "sin miembros de clase"
    assert db.scalars(select(FinancialFact)).all() == []


def test_parse_applies_scale_and_sign():
    """iXBRL declara la magnitud real en el literal escalado y negado:
    scale="3" sign="-" sobre 1.25 es -1250, no 1.25 (FIX5-5)."""
    xml = SEGMENT_INSTANCE_XML.replace(
        'contextRef="s1" unitRef="uUSD" decimals="2"',
        'contextRef="s1" unitRef="uUSD" decimals="2" scale="3" sign="-"',
    )
    facts = _parse(xml)
    assert facts[0].value == Decimal("-1250")


def test_parse_rejects_a_wrong_unitref_but_tolerates_none():
    """Un BPA etiquetado en acciones es otra magnitud: se descarta. Sin
    unitRef no hay unidad que contradecir (FIX5-5)."""
    wrong_unit = SEGMENT_INSTANCE_XML.replace('unitRef="uUSD"', 'unitRef="ushares"')
    assert _parse(wrong_unit) == []
    facts = _parse(INSTANCE_XML)  # sin unitRef en ningun hecho
    assert facts


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Tenant.__table__, Company.__table__, Document.__table__, FinancialFact.__table__],
    )
    with Session(engine) as session:
        yield session


def _company(db: Session, ticker: str = "V") -> Company:
    row = Company(
        ticker=ticker, name=f"{ticker} Inc", exchange="NYSE", currency="USD",
        sector="S", industry="I", company_type="operating", valuation_model="standard_dcf",
    )
    db.add(row)
    db.flush()
    return row


def _fake_fetchers(xml: str):
    def fetch_json(url: str) -> dict:
        if "submissions" in url:
            return {"filings": {"recent": {"form": ["10-K"], "accessionNumber": ["0001-25-000001"]}}}
        return {"directory": {"item": [{"name": "x-20250930_htm.xml"}]}}

    def fetch_bytes(url: str) -> bytes:
        return xml.encode()

    return fetch_json, fetch_bytes


def test_backfill_writes_class_a_facts_with_sec_shape(db):
    company = _company(db, "V")
    fetch_json, fetch_bytes = _fake_fetchers(INSTANCE_XML)
    result = backfill_class_based_eps(db, company, cik="0001403161", fetch_json=fetch_json, fetch_bytes=fetch_bytes)
    assert result.facts_written == 4  # eps + shares x 2 anos
    assert result.member_used == "CommonClassAMember"
    rows = db.scalars(select(FinancialFact)).all()
    by_key = {(r.metric, r.period): r for r in rows}
    assert by_key[("eps_diluted", "2025-09-30:FY")].value == Decimal("10.20")
    assert by_key[("shares_diluted", "2024-09-30:FY")].value == Decimal("2029000000")
    for row in rows:
        assert row.fiscal_quarter == "FY"
        assert row.fiscal_year == int(row.period[:4])
        assert row.source_type == "SEC"
        assert row.is_reported is True
        assert row.unit == ("USD/share" if row.metric == "eps_diluted" else "shares")
    # Nunca la clase equivocada:
    assert all(r.value != Decimal("15.95") for r in rows)


def test_backfill_dedupes_facts_repeated_across_sections(db):
    """La instancia real repite cada hecho en balance/notas con contextos
    distintos: solo puede escribirse una fila por (metrica, periodo)."""
    company = _company(db, "V")
    duplicated = INSTANCE_XML.replace(
        '<us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding contextRef="c1">1966000000</us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding>',
        '<us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding contextRef="c1">1966000000</us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding>\n'
        '  <us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding contextRef="c1">1966000000</us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding>',
    )
    fetch_json, fetch_bytes = _fake_fetchers(duplicated)
    result = backfill_class_based_eps(db, company, cik="1", fetch_json=fetch_json, fetch_bytes=fetch_bytes)
    assert result.facts_written == 4
    rows = db.scalars(select(FinancialFact)).all()
    keys = [(r.metric, r.period) for r in rows]
    assert len(keys) == len(set(keys))


def test_backfill_is_idempotent_and_preserves_existing(db):
    company = _company(db, "V")
    existing = FinancialFact(
        company_id=company.id, metric="eps_diluted", value=Decimal("9.99"),
        unit="USD/share", period="2025-09-30:FY", fiscal_year=2025,
        fiscal_quarter="FY", source_type="SEC", is_reported=True,
    )
    db.add(existing)
    db.flush()
    fetch_json, fetch_bytes = _fake_fetchers(INSTANCE_XML)
    first = backfill_class_based_eps(db, company, cik="1", fetch_json=fetch_json, fetch_bytes=fetch_bytes)
    second = backfill_class_based_eps(db, company, cik="1", fetch_json=fetch_json, fetch_bytes=fetch_bytes)
    assert first.facts_written == 3  # el 2025-09-30:FY de eps ya existia
    assert second.facts_written == 0
    kept = db.scalar(select(FinancialFact).where(
        FinancialFact.metric == "eps_diluted", FinancialFact.period == "2025-09-30:FY"))
    assert kept.value == Decimal("9.99")


def test_backfill_uses_basic_tags_when_no_diluted(db):
    company = _company(db, "BRK.B")
    fetch_json, fetch_bytes = _fake_fetchers(BRK_INSTANCE_XML)
    result = backfill_class_based_eps(db, company, cik="1067983", fetch_json=fetch_json, fetch_bytes=fetch_bytes)
    assert result.member_used == "EquivalentClassBMember"
    rows = db.scalars(select(FinancialFact)).all()
    by_metric = {r.metric: r for r in rows}
    assert by_metric["eps_diluted"].value == Decimal("41.27")  # clase B, no 61900 (clase A)
    assert by_metric["shares_diluted"].value == Decimal("2157335139")
    document = db.scalar(select(Document))
    assert document.metadata_["class_member"] == "EquivalentClassBMember"
    assert "EarningsPerShareBasic" in document.metadata_["xbrl_tags"]


def test_backfill_skips_unknown_multi_class_ticker(db):
    company = _company(db, "ZZZ")  # sin preferencia configurada
    fetch_json, fetch_bytes = _fake_fetchers(INSTANCE_XML)
    result = backfill_class_based_eps(db, company, cik="1", fetch_json=fetch_json, fetch_bytes=fetch_bytes)
    assert result.facts_written == 0
    assert result.skipped_reason == "varias clases sin preferida"
    assert db.scalars(select(FinancialFact)).all() == []


def test_read_response_decompresses_gzip():
    import gzip as _gzip

    from app.services.class_filer_eps_service import _read_response

    class _Resp:
        def __init__(self, data: bytes, encoding: str | None):
            self._data = data
            self.headers = {"Content-Encoding": encoding} if encoding else {}

        def read(self) -> bytes:
            return self._data

    payload = b'{"ok": true}'
    assert _read_response(_Resp(_gzip.compress(payload), "gzip")) == payload
    assert _read_response(_Resp(payload, None)) == payload


def _with_extra_scope(xml, scope):
    return xml.replace(
        '<explicitMember dimension="v:CommonClassAxis">us-gaap:CommonClassAMember</explicitMember>',
        '<explicitMember dimension="v:CommonClassAxis">us-gaap:CommonClassAMember</explicitMember>' + scope,
    )


@pytest.mark.parametrize('scope', [
    '<explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">v:DomesticMember</explicitMember>',
    '<explicitMember dimension="v:GeographyAxis">v:EuropeMember</explicitMember>',
    '<typedMember dimension="v:BusinessAxis"><v:Business>Example</v:Business></typedMember>',
    '<explicitMember dimension="v:OtherClassAxis">v:CommonClassBMember</explicitMember>',
])
def test_backfill_class_plus_extra_scope_cannot_shadow_total(db, scope):
    # Actual service, synthetic filing. Bad scoped facts deliberately come first.
    scoped = _with_extra_scope(INSTANCE_XML, scope).replace('10.20', '1.25')
    # Change scoped IDs so their contexts cannot replace the true class totals.
    for context in ('c1', 'c2', 'c3', 'c4', 'c5'):
        scoped = scoped.replace('"' + context + '"', '"scoped-' + context + '"')
    # Keep a single root and insert the scoped contents before the original.
    import xml.etree.ElementTree as ET
    root = ET.fromstring(INSTANCE_XML)
    extra = ET.fromstring(scoped)
    for child in reversed(list(extra)):
        root.insert(0, child)
    fetch_json, fetch_bytes = _fake_fetchers(ET.tostring(root).decode())
    result = backfill_class_based_eps(db, _company(db), cik='1', fetch_json=fetch_json, fetch_bytes=fetch_bytes)
    assert result.facts_written == 4
    rows = db.scalars(select(FinancialFact)).all()
    assert next(r.value for r in rows if r.metric == 'eps_diluted' and r.fiscal_year == 2025) == Decimal('10.20')


def test_backfill_class_plus_segment_only_writes_nothing(db):
    xml = _with_extra_scope(INSTANCE_XML, '<explicitMember dimension="v:SegmentAxis">v:DomesticMember</explicitMember>')
    # Remove class B so no eligible fallback class remains.
    xml = xml.replace('v:CommonClassBMember', 'v:NotAClassMember')
    fetch_json, fetch_bytes = _fake_fetchers(xml)
    result = backfill_class_based_eps(db, _company(db), cik='1', fetch_json=fetch_json, fetch_bytes=fetch_bytes)
    assert result.facts_written == 0
    assert db.scalars(select(FinancialFact)).all() == []
