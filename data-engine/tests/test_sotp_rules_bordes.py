"""Bordes de sotp_rules: parsing de cifras, contexto de ingresos, anclas

trimestrales, huella de fuentes y dilución. Funciones puras, sin BD.
"""

from __future__ import annotations

import math

from app.services.expert_team import sotp_rules as sr


def test_as_float_ambos_separadores():
    # Punto como decimal (estilo US) y coma como decimal (estilo ES).
    assert sr._as_float("1,234.5") == 1234.5
    assert sr._as_float("1.234,5") == 1234.5


def test_as_float_token_irrecuperable():
    assert sr._as_float("1,2,3") is None


def test_figures_in_text_omite_cifra_irrecuperable():
    # El separador de miles de espacio duro casa con _NUMBER pero _as_float no lo limpia.
    assert sr.figures_in_text("valor 1 234 million") == []


def test_figure_supported_rechaza_importes_no_positivos():
    assert sr.figure_supported(0, ["100 million"]) is False
    assert sr.figure_supported(None, ["100 million"]) is False
    assert sr.figure_supported(math.inf, ["100 million"]) is False
    assert sr.figure_supported(-5, ["100 million"]) is False


def test_windows_with_omite_cifra_irrecuperable():
    assert sr._windows_with(100.0, "habia 1 234 cosas") == []


def test_revenue_context_sin_contexto():
    assert sr.revenue_context(100.0, []) == "sin contexto de la cifra"


def test_revenue_context_pasaje_sin_palabra_de_ingresos():
    motivo = sr.revenue_context(100.0, ["El valor registrado fue 100 million."])
    assert motivo == "el pasaje citado no habla de ingresos ni de un contrato de servicio"


def test_raw_numbers_descarta_anios_y_cifras_con_escala():
    assert sr._raw_numbers("en 2024 se cerraron 5 billion") == []


def test_quarterly_report_anchor_toma_el_trimestre():
    anchor = {
        "type": "reportado",
        "period": "anual",
        "amount_millions": 100.0,
        "quote": "Ingresos del trimestre 100",
        "sources": [{"label": "10-Q 2024"}],
    }
    out, nota = sr.quarterly_report_anchor(anchor)
    assert out["period"] == "trimestral"
    assert nota == "cifra de un 10-Q tomada como anual: es la del trimestre"


def test_quarterly_report_anchor_sin_cifra_en_la_cita():
    anchor = {
        "type": "reportado",
        "period": "anual",
        "amount_millions": 100.0,
        "quote": "sin cifras recuperables",
        "sources": [{"label": "10-Q 2024"}],
    }
    out, nota = sr.quarterly_report_anchor(anchor)
    assert out == anchor
    assert nota is None


def test_fingerprint_changes_sin_previa():
    assert sr.fingerprint_changes(None, {"rules_version": "v1"}) == []


def test_fingerprint_changes_versiones():
    out = sr.fingerprint_changes(
        {"rules_version": "v1", "prompt_version": "p1", "sources": [], "hash": "h"},
        {"rules_version": "v2", "prompt_version": "p2", "sources": [], "hash": "h"},
    )
    assert "reglas v1 → v2" in out
    assert "prompt p1 → p2" in out


def test_fingerprint_changes_fuentes():
    previa = {"rules_version": "v1", "prompt_version": "p1", "hash": "h",
              "sources": ["sec:facts|2024-01-01|Informe A", "news:x|2024-01-02|Noticia vieja"]}
    actual = {"rules_version": "v1", "prompt_version": "p1", "hash": "h",
              "sources": ["sec:facts|2024-02-01|Informe A", "doc:y|2024-02-02|Documento nuevo"]}
    out = sr.fingerprint_changes(previa, actual)
    assert "actualizado: Informe A (2024-02-01)" in out
    assert "nuevo: Documento nuevo" in out
    assert "retirado: Noticia vieja" in out


def test_fingerprint_changes_solo_hash():
    previa = {"rules_version": "v1", "prompt_version": "p1", "sources": ["s:k|T"], "hash": "h1"}
    actual = {"rules_version": "v1", "prompt_version": "p1", "sources": ["s:k|T"], "hash": "h2"}
    out = sr.fingerprint_changes(previa, actual)
    assert out == ["cambió el contenido de una fuente ya usada (hechos SEC, documentos o noticias)"]


def test_historical_growth_cagr_dos_anios():
    rows = [
        {"revenue_millions": 100.0, "period_end": "2023-12-31"},
        {"revenue_millions": 121.0, "period_end": "2024-12-31"},
    ]
    assert sr.historical_growth(rows) == 0.20999999999999996


def test_burn_gap_unknown_falta_la_caja():
    motivo = sr.burn_gap_unknown({"burns_cash": True, "annual_burn_millions": 50.0, "cash_millions": None})
    assert motivo is not None and "no se calcula" in motivo


def test_code_dilution_sin_precio_no_calcula():
    assert sr.code_dilution({"ticker": "X", "price": None}, 3) == []
    assert sr.code_dilution({"ticker": "X", "price": 0}, 3) == []
