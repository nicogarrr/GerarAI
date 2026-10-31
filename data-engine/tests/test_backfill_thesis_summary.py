"""Tests del backfill de summaries de ThesisChange (idempotencia y detección)."""
from app.services.text_clip import normalize_scraped_text


def test_normalize_es_idempotente():
    raw = "…StockCurrent Price: $210. 32Target Price (Mid): ~$794Street Target:…What Happened?Coherent (COHR:NYSE) fell 11."
    once = normalize_scraped_text(raw)
    assert normalize_scraped_text(once) == once
    assert once != raw


def test_deteccion_de_filas_sucias():
    sucio = "…StockCurrent Price: $210. 32Target Price (Mid): ~$794Street"
    limpio = "Apple (AAPL) cae un 3,5 % tras resultados."
    assert normalize_scraped_text(sucio) != sucio
    assert normalize_scraped_text(limpio) == limpio
    assert normalize_scraped_text("") == ""
