"""Sección 20 (Fuentes): el detalle de fundamentales no puede contradecirse.

Antes salía «Fundamentales: conseguido (SEC EDGAR companyfacts, 0 hechos:
cash_and_equivalents, ...)»: decía 0 hechos mientras listaba métricas. El
refresco sin novedades (todo ya importado) debe decirlo como tal.
"""

from app.services.thesis_service import ThesisService


def _block(**kw):
    base = {
        "status": "ok",
        "source": "SEC EDGAR companyfacts",
        "metrics": ["revenue", "cash_and_equivalents"],
    }
    base.update(kw)
    return base


def test_fundamentals_refresh_without_new_facts_says_already_imported():
    detail = ThesisService()._source_ok_detail(
        "fundamentals", _block(facts_imported=0, already_present=42)
    )
    assert "0 hechos:" not in detail
    assert "42 hechos ya importados" in detail
    assert "revenue" in detail  # las métricas cubiertas se siguen nombrando


def test_fundamentals_fresh_import_counts_new_and_existing():
    detail = ThesisService()._source_ok_detail(
        "fundamentals", _block(facts_imported=5, already_present=10)
    )
    assert "5 hechos importados" in detail
    assert "10 ya presentes" in detail


def test_sources_markdown_keeps_conseguido_without_zero_facts_contradiction():
    md = ThesisService()._sources_markdown(
        {"fundamentals": _block(facts_imported=0, already_present=42)}
    )
    assert "Fundamentales: conseguido" in md
    assert "0 hechos:" not in md
