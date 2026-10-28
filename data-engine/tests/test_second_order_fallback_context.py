"""Fallback determinista de 2o orden: contexto con fuente y fecha, sin plan
y sin valor justo.

Cuando no hay via LLM (cuota agotada, proveedor caido o desactivado) la
salida es ``analyze_second_order(..., use_llm=False)``: la via DETERMINISTA.
Estos tests fijan lo que ese contexto debe declarar (fuente con fecha) y lo
que nunca debe afirmar (plan de inversion ni valor justo). Sin LLM real, sin
red, sin gasto. La generacion real con cuota agotada NO se da por probada.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, NewsEvent
from app.services import second_order_news_service as service


def _companies():
    return [
        Company(
            ticker="GRID",
            name="Grid Co",
            exchange="NYSE",
            currency="USD",
            sector="Utilities",
            industry="Electric Utilities",
            company_type="holding",
            valuation_model="unassigned",
            special_sources=[],
            special_risks=[],
            factor_tags=[],
        ),
        Company(
            ticker="OIL",
            name="Oil Co",
            exchange="NYSE",
            currency="USD",
            sector="Energy",
            industry="Oil & Gas",
            company_type="holding",
            valuation_model="unassigned",
            special_sources=[],
            special_risks=[],
            factor_tags=[],
        ),
    ]


def _db_and_event(monkeypatch, **event_kwargs):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = "tenant-test"
    kwargs = dict(
        title="Electric trucks require 350 TWh of electrification",
        summary="A claim about electric trucks",
        source="GDELT",
        url="https://example.test/story",
        date=datetime(2026, 9, 27, 12, 30),
        metadata_={"date_source": "source"},
    )
    kwargs.update(event_kwargs)
    event = NewsEvent(**kwargs)
    db.add_all([*_companies(), event])
    db.commit()
    monkeypatch.setattr(
        service,
        "_jev_marker",
        lambda theme: {
            "direction": None,
            "confidence": None,
            "backend": None,
        },
    )
    return db, event


def test_fallback_declares_source_with_utc_date(monkeypatch):
    db, event = _db_and_event(monkeypatch)
    result = service.analyze_second_order(db, event, use_llm=False)
    # La fecha de la fuente se declara y se normaliza a UTC (el evento la trae naive).
    assert result["source"]["published_at"] == "2026-09-27T12:30:00+00:00"
    assert result["source"]["url"] == "https://example.test/story"
    assert result["source"]["name"] == "GDELT"
    assert result["candidates"], "el fixture de camiones electricos debe casar con GRID/OIL"
    for candidate in result["candidates"]:
        assert candidate["sources"][0]["published_at"] == "2026-09-27T12:30:00+00:00"
        assert candidate["sources"][0]["url"] == "https://example.test/story"
    db.close()


def test_fallback_omits_date_when_not_sourced(monkeypatch):
    db, event = _db_and_event(monkeypatch, metadata_={"date_source": "ingested_at_fallback"})
    result = service.analyze_second_order(db, event, use_llm=False)
    # Fecha no declarada por la fuente: N/D honesto, no la de ingesta.
    assert result["source"]["published_at"] is None
    for candidate in result["candidates"]:
        assert candidate["sources"][0]["published_at"] is None
    db.close()


def test_fallback_never_emits_plan_or_fair_value(monkeypatch):
    db, event = _db_and_event(monkeypatch)
    result = service.analyze_second_order(db, event, use_llm=False)
    assert result["mode"] == "determinista"
    assert result["llm_model"] is None
    assert result["llm_quota"] is None
    assert result["status"] == "hipótesis_no_verificadas"
    assert result["source_verified"] is False

    # Estructura: ninguna clave de plan ni de valor justo, en ningun nivel.
    def keys_deep(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield str(key)
                yield from keys_deep(value)
        elif isinstance(node, list):
            for item in node:
                yield from keys_deep(item)

    keys = {key.lower() for key in keys_deep(result)}
    assert not any("plan" in key or "fair" in key for key in keys), keys
    # Texto: sin afirmaciones de valor justo ni objetivos; con el aviso de hipotesis.
    text = json.dumps(result, ensure_ascii=False).lower()
    for forbidden in (
        "valor justo",
        "fair value",
        "price target",
        "precio objetivo",
        "plan de inversión",
        "recomendación de compra",
        "recomendación de venta",
    ):
        assert forbidden not in text
    assert result["warning"].startswith("Solo hipótesis")
    db.close()


def test_fallback_candidates_carry_unverified_limitations(monkeypatch):
    db, event = _db_and_event(monkeypatch)
    result = service.analyze_second_order(db, event, use_llm=False)
    assert result["candidates"]
    for candidate in result["candidates"]:
        assert candidate["status"] == "hipótesis_no_verificada"
        assert candidate["confidence"] is None
        assert candidate["jev_direction"] is None
        limitations = " ".join(candidate["limitations"]).lower()
        assert "no hechos verificados" in limitations
        assert "no acredita ingresos" in limitations
        assert candidate["causal_chain"], "toda hipotesis declara su cadena causal"
    db.close()
