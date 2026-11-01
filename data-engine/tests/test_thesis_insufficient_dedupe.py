"""QA-6: insufficient_data equivalentes (solo cambia el precio) no apilan versiones."""
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import main
from app.core.database import SessionLocal, init_db
from app.models import Company, MarketPrice, NewsEvent, ThesisVersion
from app.seed import seed
from app.services.thesis_service import ThesisService
from tests import test_thesis_auto_ingest as base
from tests.auth_helpers import csrf_client


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    base._clean_asts_evidence()


def _versions():
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == "ASTS"))
        rows = db.scalars(
            select(ThesisVersion).where(ThesisVersion.company_id == company.id).order_by(ThesisVersion.version)
        ).all()
        return [(r.id, r.version, r.status, r.updated_at) for r in rows]
    finally:
        db.close()


def _new_price():
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == "ASTS"))
        db.add(MarketPrice(company_id=company.id, date=date.today() + timedelta(days=30),
                           open=1, high=1, low=1, close=31.25, source="test"))
        db.commit()
    finally:
        db.close()


def test_generate_dedupes_price_only_change_but_not_material_or_forced(monkeypatch):
    init_db()
    seed()
    base._clean_asts_evidence()
    base._mock_all_sources(monkeypatch)
    base._seed_evidence_rows()
    client = csrf_client(main.app)

    first = client.post("/api/thesis/generate", json={"ticker": "ASTS", "force_new_version": True}).json()
    assert first["status"] == "insufficient_data"
    assert "insufficient_signature" in (first["valuation_basis"] or {})
    before = _versions()

    # Solo cambia el precio: misma firma => no hay version nueva.
    _new_price()
    again = client.post("/api/thesis/generate", json={"ticker": "ASTS"}).json()
    after_price = _versions()
    assert again["id"] == first["id"]
    assert [v[:3] for v in after_price] == [v[:3] for v in before]

    # Noticia nueva = evidencia material: version nueva.
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == "ASTS"))
        db.add(NewsEvent(company_id=company.id, date=datetime.now(UTC), title="ASTS nueva noticia material",
                         source="press", url="https://example.com/n2", summary="x", event_type="partnership",
                         materiality_score=8, impact_direction="positive"))
        db.commit()
    finally:
        db.close()
    after_news = client.post("/api/thesis/generate", json={"ticker": "ASTS"}).json()
    assert after_news["id"] != first["id"]
    assert len(_versions()) == len(before) + 1

    # force_new_version siempre crea.
    forced = client.post("/api/thesis/generate", json={"ticker": "ASTS", "force_new_version": True}).json()
    assert forced["id"] not in (first["id"], after_news["id"])


def _row(status, basis):
    return SimpleNamespace(status=status, valuation_basis=basis)


SIG = {"reason": "r", "engine": "e", "method": "m", "missing_inputs": ["wacc"], "material_fp": "x"}


def test_signature_requires_every_field_equal_and_explicit_previous():
    same = _row("insufficient_data", {"insufficient_signature": dict(SIG)})
    assert ThesisService._same_insufficient_signature(same, dict(SIG))
    for key, other in (("reason", "otro"), ("engine", "otro"), ("method", "otro"),
                       ("missing_inputs", ["capex"]), ("material_fp", "y")):
        assert not ThesisService._same_insufficient_signature(same, {**SIG, key: other}), key
    # Sin evidencia previa explicita: nunca se deduplica.
    assert not ThesisService._same_insufficient_signature(_row("insufficient_data", None), dict(SIG))
    assert not ThesisService._same_insufficient_signature(_row("insufficient_data", {}), dict(SIG))
    assert not ThesisService._same_insufficient_signature(_row("draft", {"insufficient_signature": dict(SIG)}), dict(SIG))
    assert not ThesisService._same_insufficient_signature(same, None)




def _setup_first(monkeypatch):
    init_db()
    seed()
    base._clean_asts_evidence()
    base._mock_all_sources(monkeypatch)
    base._seed_evidence_rows()
    client = csrf_client(main.app)
    first = client.post("/api/thesis/generate", json={"ticker": "ASTS", "force_new_version": True}).json()
    assert first["status"] == "insufficient_data"
    return client, first


def _patch_valuation(monkeypatch, **trace_changes):
    orig = ThesisService.__init__

    def init(self, *a, **k):
        orig(self, *a, **k)
        vs = self.valuation_service
        real = vs.value_company

        def patched(db, company):
            out = real(db, company)
            out.setdefault("trace", {}).update(trace_changes.get("trace", {}))
            if "missing_inputs" in trace_changes:
                out["missing_inputs"] = trace_changes["missing_inputs"]
            return out

        vs.value_company = patched

    monkeypatch.setattr(ThesisService, "__init__", init)


@pytest.mark.parametrize(
    "changes",
    [
        {"trace": {"reason": "motivo distinto"}},
        {"trace": {"method": "otro_metodo"}},
        {"missing_inputs": ["capex_distinto"]},
    ],
)
def test_generate_same_fingerprint_but_different_reason_method_or_inputs_creates_version(monkeypatch, changes):
    client, first = _setup_first(monkeypatch)
    n = len(_versions())
    _patch_valuation(monkeypatch, **changes)
    out = client.post("/api/thesis/generate", json={"ticker": "ASTS"}).json()
    assert out["id"] != first["id"]
    assert len(_versions()) == n + 1


def test_generate_legacy_insufficient_without_signature_creates_version(monkeypatch):
    client, first = _setup_first(monkeypatch)
    db = SessionLocal()
    try:
        row = db.get(ThesisVersion, first["id"])
        basis = dict(row.valuation_basis or {})
        basis.pop("insufficient_signature", None)
        row.valuation_basis = basis
        db.commit()
    finally:
        db.close()
    n = len(_versions())
    out = client.post("/api/thesis/generate", json={"ticker": "ASTS"}).json()
    assert out["id"] != first["id"]
    assert len(_versions()) == n + 1


def test_insufficient_fingerprint_ignores_price_but_valued_thesis_keeps_it(monkeypatch):
    client, first = _setup_first(monkeypatch)
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == "ASTS"))
        service = ThesisService()
        insufficient = {"status": "insufficient_data", "trace": {}}
        valued = {"status": "ok", "trace": {}}
        before_insufficient = service._input_fingerprint(db, company, insufficient, {}, include_price=False)
        before_valued = service._input_fingerprint(db, company, valued, {}, include_price=True)
    finally:
        db.close()
    _new_price()
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == "ASTS"))
        service = ThesisService()
        assert service._input_fingerprint(
            db, company, {"status": "insufficient_data", "trace": {}}, {}, include_price=False
        ) == before_insufficient
        assert service._input_fingerprint(
            db, company, {"status": "ok", "trace": {}}, {}, include_price=True
        ) != before_valued
    finally:
        db.close()


def test_forced_insufficient_versions_share_fingerprint_when_only_price_changes(monkeypatch):
    client, first = _setup_first(monkeypatch)
    _new_price()
    forced = client.post("/api/thesis/generate", json={"ticker": "ASTS", "force_new_version": True}).json()
    assert forced["id"] != first["id"]
    assert forced["status"] == "insufficient_data"
    assert forced["input_fingerprint"] == first["input_fingerprint"]
