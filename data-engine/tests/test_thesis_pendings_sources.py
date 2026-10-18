"""La lista N/D de la tesis usa las mismas fuentes resueltas que la tabla de
inputs: un input con fact documentado (OFICIAL o derivado con URL) no se declara
N/D por no haber pasado las fuentes (bug: classify_origin recibia sources={})."""

from app.services.thesis_service import ThesisService

OFFICIAL_URL = "https://www.sec.gov/Archives/edgar/data/1780312/000119312526342550/asts-20260630.htm"


def _model() -> dict:
    return {
        "driver_model": [
            {
                "key": "satellites",
                "status": "sourced",
                "value": 9.0,
                "unit": "count",
                "source_fact_ids": [11],
                "confidence": 0.9,
                "trace": {"period": "2026-06-30:Q2"},
            }
        ],
        "assumptions": {
            "net_margin": {
                "value": -3.2,
                "unit": "decimal",
                "source_type": "financial_facts",
                "basis": "median of latest 2 annual net_margin observations",
                "source_fact_ids": [12],
                "confidence": 0.8,
            },
            "terminal_growth": {
                "value": 0.03,
                "unit": "decimal",
                "source_type": "model_policy",
                "basis": "terminal growth policy from company framework",
                "source_fact_ids": [],
                "confidence": 0.4,
            },
        },
    }


FACT_SOURCES = {
    11: {
        "metric": "satellites",
        "fact_value": 9.0,
        "unit": "count",
        "period": "2026-06-30:Q2",
        "is_reported": True,
        "url": OFFICIAL_URL,
        "date": "2026-08-10",
        "title": "ASTS 10-Q",
        "source_type": "primary_official",
    },
    12: {
        "metric": "net_income",
        "fact_value": 1.0,
        "unit": "USD",
        "period": "2025-12-31:FY",
        "is_reported": True,
        "url": OFFICIAL_URL,
        "date": "2026-03-01",
        "title": "ASTS 10-K",
        "source_type": "primary_official",
    },
}


def test_pendings_without_resolved_sources_marks_everything_nd():
    text = ThesisService()._pendings_markdown({}, _model(), {})
    assert "`satellites`: N/D" in text
    assert "`net_margin`: N/D" in text


def test_pendings_with_resolved_sources_keeps_only_real_nd():
    text = ThesisService()._pendings_markdown({}, _model(), {}, FACT_SOURCES)
    assert "`satellites`" not in text
    assert "`net_margin`" not in text
    assert "`terminal_growth`: N/D" in text
