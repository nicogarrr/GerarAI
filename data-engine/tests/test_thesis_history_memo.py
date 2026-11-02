"""Historial de tesis + memo Markdown descargable (solo lectura persistida)."""

from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.core.database import SessionLocal
from app.models import (
    Claim,
    ClaimEvidence,
    Company,
    FundamentalModelVersion,
    ThesisDiff,
    ThesisSection,
    ThesisVersion,
)
from app.seed import seed

TICKER = "ASTS"
# Modelo publicable propio del test (la DB de test es compartida: se borra por huella).
MODEL_FINGERPRINT = "memo-test-input"


def _clean() -> None:
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == TICKER))
        if company:
            for model in (ClaimEvidence,):
                db.query(model).delete()
            db.query(Claim).delete()
            db.query(ThesisSection).delete()
            db.query(ThesisDiff).delete()
            db.query(ThesisVersion).filter(ThesisVersion.company_id == company.id).delete()
            db.query(FundamentalModelVersion).filter(
                FundamentalModelVersion.input_fingerprint == MODEL_FINGERPRINT
            ).delete()
            db.commit()
    finally:
        db.close()


def _seed_two_versions() -> tuple[int, int]:
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.ticker == TICKER))
        v1 = ThesisVersion(
            company_id=company.id, version=1, status="published",
            thesis_markdown="# v1", executive_summary="primera",
            rating="watch", data_confidence_score=60, source_coverage_score=70,
            red_team_score=80, valuation_risk_score=40,
            hypothesis="La red directa a celular se monetiza",
            catalysts=[{"title": "Lanzamiento comercial", "date": "2027"}],
            invalidation_criteria=["Retrasos regulatorios"],
            scenario_probabilities={"bear": 0.2, "base": 0.6, "bull": 0.2},
            bear_value=10, base_value=30, bull_value=60,
        )
        v2 = ThesisVersion(
            company_id=company.id, version=2, status="draft",
            thesis_markdown="# v2", executive_summary="segunda",
            rating="buy", data_confidence_score=65, source_coverage_score=72,
            red_team_score=82, valuation_risk_score=38,
        )
        # v1 está «published» con cifras: la puerta de publicación exige un
        # modelo publicable vigente para mostrarla (si no, sale archivada).
        model = FundamentalModelVersion(
            company_id=company.id, version=1, engine_version="test", algorithm_version="test",
            framework_key="dcf", horizon_years=10, status="ok", publishable=True,
            input_fingerprint=MODEL_FINGERPRINT, forecast_fingerprint="forecast",
            market_snapshot_fingerprint="market", valuation_snapshot_fingerprint="valuation",
        )
        db.add_all([v1, v2, model])
        db.flush()
        db.add(ThesisDiff(
            company_id=company.id, from_version_id=v1.id, to_version_id=v2.id,
            change_summary="Mejora el guidance de ingresos",
            affected_assumptions=["revenue_cagr"], rating_changed=True,
        ))
        db.add(ThesisSection(
            thesis_version_id=v1.id, company_id=company.id,
            section_key="moat", title="Foso competitivo", body="Espectro y satelites.",
            status="approved", order_index=1,
        ))
        claim = Claim(
            company_id=company.id, thesis_version_id=v1.id,
            statement="Cobertura en 50 paises", claim_type="thesis",
        )
        db.add(claim)
        db.flush()
        db.add(ClaimEvidence(
            claim_id=claim.id, source_url="https://example.com/cobertura",
            source_tier="primary", summary="Presentacion de la compania",
        ))
        db.commit()
        return v1.id, v2.id
    finally:
        db.close()


def test_history_returns_versions_with_diffs():
    seed()
    _clean()
    v1_id, v2_id = _seed_two_versions()
    client = TestClient(main.app)
    response = client.get(f"/api/thesis/{TICKER}/history")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    newest, oldest = payload["history"][0], payload["history"][1]
    assert newest["version"] == 2 and newest["status"] == "draft"
    assert newest["diff"]["rating_changed"] is True
    assert "guidance" in newest["diff"]["change_summary"]
    assert oldest["version"] == 1 and oldest["status"] == "published"
    assert oldest["diff"] is None
    _clean()


def test_memo_markdown_download_contains_professional_fields():
    seed()
    _clean()
    v1_id, _ = _seed_two_versions()
    # La ultima version es v2 (draft, sin campos profesionales); para probar
    # el memo completo, subimos su version number a 0 y dejamos v1 como latest.
    db = SessionLocal()
    try:
        db.query(ThesisVersion).filter(ThesisVersion.version == 2).update({"version": 0})
        db.commit()
    finally:
        db.close()
    client = TestClient(main.app)
    response = client.get(f"/api/thesis/{TICKER}/memo.md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment" in response.headers["content-disposition"]
    body = response.text
    assert f"Memo de tesis — {TICKER}" in body
    assert "La red directa a celular se monetiza" in body
    assert "| Bajista | $10.00 | 20 % |" in body
    assert "Retrasos regulatorios" in body
    assert "Foso competitivo" in body
    assert "https://example.com/cobertura" in body
    assert "NO es asesoramiento financiero" in body
    _clean()


def test_memo_404_without_thesis():
    seed()
    _clean()
    client = TestClient(main.app)
    response = client.get(f"/api/thesis/{TICKER}/memo.md")
    assert response.status_code == 404


def test_memo_markdown_in_english_with_english_selected(monkeypatch):
    from app.core.config import get_settings

    seed()
    _clean()
    _seed_two_versions()
    db = SessionLocal()
    try:
        db.query(ThesisVersion).filter(ThesisVersion.version == 2).update({"version": 0})
        db.commit()
    finally:
        db.close()
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        english = client.get(f"/api/thesis/{TICKER}/memo.md", headers={"x-gerarai-language": "en"}).text
        spanish = client.get(f"/api/thesis/{TICKER}/memo.md", headers={"x-gerarai-language": "es"}).text
    finally:
        monkeypatch.delenv("I18N_GENERATION_ENABLED")
        get_settings.cache_clear()
        _clean()
    assert f"Thesis memo — {TICKER}" in english
    assert "| Bear | $10.00 | 20% |" in english
    assert "La red directa a celular se monetiza" in english
    assert "NOT financial advice" in english
    assert f"Memo de tesis — {TICKER}" in spanish and "| Bajista | $10.00 | 20 % |" in spanish
