"""Huecos de cobertura en reviews (lote 11).

Medicion previa (mismo metodo, tests que referencian el modulo): reviews
41,7 %. Se cubren: list_reviews (404 de compania y filtro por estado),
update_review (404, transicion con y sin notas en el cuerpo) y
scan_contradictions (404 de compania, documento y noticia, y los tres
caminos de escaneo). Todo con db y servicios doblados: sin sqlite.

Que NO se prueba aqui: nada de HTTP ni auth; ninguna base de datos real
(las consultas SQL se construyen pero van contra una db doblada, asi que
el filtrado real por SQL NO se prueba); ReviewAlertService y
ClaimIntelligenceService van doblados (no se prueba la transicion de
estado real ni el escaneo de contradicciones, solo la delegacion); y
resolve_company va doblado.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import reviews as reviews_route
from app.schemas import ContradictionScanRequest, ResearchReviewUpdate

COMPANY = SimpleNamespace(id=9, ticker="ASTS")


def _db():
    db = Mock()
    db.info = {"tenant_id": 1}
    return db


# --- list_reviews -----------------------------------------------------------


def test_lista_compania_desconocida_es_404(monkeypatch):
    monkeypatch.setattr(reviews_route, "resolve_company", lambda db, t: None)
    with pytest.raises(HTTPException) as exc:
        reviews_route.list_reviews(ticker="NOPE", status="open", limit=10, db=_db())
    assert exc.value.status_code == 404


def test_lista_estado_invalido_es_400():
    with pytest.raises(HTTPException) as exc:
        reviews_route.list_reviews(ticker=None, status="pendiente", limit=10, db=_db())
    assert exc.value.status_code == 400


def test_lista_devuelve_las_reviews(monkeypatch):
    review = SimpleNamespace(id=1)
    monkeypatch.setattr(reviews_route, "resolve_company", lambda db, t: COMPANY)
    db = _db()
    db.scalars.return_value.all.return_value = [review]
    assert reviews_route.list_reviews(ticker="ASTS", status="open", limit=10, db=db) == [review]


# --- update_review ------------------------------------------------------------


def test_update_review_inexistente_es_404():
    db = _db()
    db.get.return_value = None
    payload = ResearchReviewUpdate(status="approved")
    with pytest.raises(HTTPException) as exc:
        reviews_route.update_review(5, payload, db=db)
    assert exc.value.status_code == 404


def test_update_solo_estado_conserva_las_notas(monkeypatch):
    """PATCH sin resolution_notes: las notas actuales se conservan."""
    transiciones = []
    monkeypatch.setattr(
        reviews_route,
        "ReviewAlertService",
        lambda: SimpleNamespace(
            transition_review=lambda review, status, resolution_notes: transiciones.append(
                (status, resolution_notes)
            )
        ),
    )
    review = SimpleNamespace(resolution_notes="nota previa")
    db = _db()
    db.get.return_value = review
    payload = ResearchReviewUpdate(status="approved")
    result = reviews_route.update_review(5, payload, db=db)
    assert transiciones == [("approved", "nota previa")]
    db.commit.assert_called_once()
    assert result is review


def test_update_con_null_explicito_borra_las_notas(monkeypatch):
    """PATCH con resolution_notes=null: las notas se borran (None)."""
    transiciones = []
    monkeypatch.setattr(
        reviews_route,
        "ReviewAlertService",
        lambda: SimpleNamespace(
            transition_review=lambda review, status, resolution_notes: transiciones.append(
                (status, resolution_notes)
            )
        ),
    )
    review = SimpleNamespace(resolution_notes="nota previa")
    db = _db()
    db.get.return_value = review
    payload = ResearchReviewUpdate(status="resolved", resolution_notes=None)
    reviews_route.update_review(5, payload, db=db)
    assert transiciones == [("resolved", None)]


# --- scan_contradictions -------------------------------------------------------


def test_scan_compania_desconocida_es_404(monkeypatch):
    monkeypatch.setattr(reviews_route, "resolve_company", lambda db, t: None)
    payload = ContradictionScanRequest(ticker="NOPE")
    with pytest.raises(HTTPException) as exc:
        reviews_route.scan_contradictions(payload, db=_db())
    assert exc.value.status_code == 404


def test_scan_documento_inexistente_es_404(monkeypatch):
    monkeypatch.setattr(reviews_route, "resolve_company", lambda db, t: COMPANY)
    db = _db()
    db.scalar.return_value = None
    payload = ContradictionScanRequest(ticker="ASTS", document_id=3)
    with pytest.raises(HTTPException) as exc:
        reviews_route.scan_contradictions(payload, db=db)
    assert exc.value.status_code == 404


def test_scan_documento_delega_en_inteligencia(monkeypatch):
    monkeypatch.setattr(reviews_route, "resolve_company", lambda db, t: COMPANY)
    escaneos = []
    monkeypatch.setattr(
        reviews_route,
        "ClaimIntelligenceService",
        lambda: SimpleNamespace(
            scan_document=lambda db, doc, auto_apply: escaneos.append(auto_apply) or {"ok": 1}
        ),
    )
    db = _db()
    db.scalar.return_value = SimpleNamespace(id=3)
    payload = ContradictionScanRequest(ticker="ASTS", document_id=3, create_reviews=False)
    assert reviews_route.scan_contradictions(payload, db=db) == {"ok": 1}
    assert escaneos == [False]


def test_scan_noticia_inexistente_es_404(monkeypatch):
    monkeypatch.setattr(reviews_route, "resolve_company", lambda db, t: COMPANY)
    db = _db()
    db.scalar.return_value = None
    payload = ContradictionScanRequest(ticker="ASTS", news_event_id=7)
    with pytest.raises(HTTPException) as exc:
        reviews_route.scan_contradictions(payload, db=db)
    assert exc.value.status_code == 404


def test_scan_noticia_compone_el_texto(monkeypatch):
    monkeypatch.setattr(reviews_route, "resolve_company", lambda db, t: COMPANY)
    visto = {}

    def scan_text(db, company, text, source_type, source_url, source_reference, auto_apply):
        visto.update(text=text, source_type=source_type, ref=source_reference)
        return {"ok": 2}

    monkeypatch.setattr(
        reviews_route, "ClaimIntelligenceService", lambda: SimpleNamespace(scan_text=scan_text)
    )
    news = SimpleNamespace(id=7, title="Resultados", summary="Suben", source="sec", url="u")
    db = _db()
    db.scalar.return_value = news
    payload = ContradictionScanRequest(ticker="ASTS", news_event_id=7)
    assert reviews_route.scan_contradictions(payload, db=db) == {"ok": 2}
    assert visto["text"] == "Resultados. Suben"
    assert visto["ref"] == {"type": "news_event", "id": 7}


def test_scan_sin_objetivo_escanea_claims_viejos(monkeypatch):
    monkeypatch.setattr(reviews_route, "resolve_company", lambda db, t: COMPANY)
    monkeypatch.setattr(
        reviews_route,
        "ClaimIntelligenceService",
        lambda: SimpleNamespace(scan_stale_claims=lambda db, company: {"stale": 4}),
    )
    payload = ContradictionScanRequest(ticker="ASTS")
    assert reviews_route.scan_contradictions(payload, db=_db()) == {"stale": 4}
