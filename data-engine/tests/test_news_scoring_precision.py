"""QA ficha/Seguir: ruido a materialidad 6-10 y sentimiento invertido.

Casos del hallazgo: «Reese Witherspoon» y «Morgan Stanley» marcadas 6-10 por
keywords sueltas, y «preorders fuertes» con sentimiento negativo. El scoring
ahora exige frases con contexto para lo ambiguo.
"""

import pytest

from app.services.materiality_service import (
    MATERIAL_KEYWORDS,
    MaterialityService,
    _has_phrase,
    _has_term,
)


def _types(text: str) -> list[str]:
    return [
        t
        for t, kws in MATERIAL_KEYWORDS.items()
        if any(_has_term(text.lower(), k) for k in kws)
    ]


def _direction(text: str) -> str:
    return MaterialityService()._impact_direction(text.lower())


@pytest.mark.parametrize(
    "text",
    [
        "Reese Witherspoon launches lifestyle brand",
        "Celebrity chef launches cookware line",
        "Verizon launches generous customer perks",
    ],
)
def test_celebrity_and_perk_launches_are_not_contract_events(text):
    assert "contract" not in _types(text)


@pytest.mark.parametrize(
    "text",
    [
        "Company launches new satellites",
        "AST SpaceMobile product launch scheduled",
        "Firm wins contract award with the DoD",
        "Vendor secures new customers in Europe",
    ],
)
def test_real_business_events_still_match_contract(text):
    assert "contract" in _types(text)


def test_morgan_stanley_price_target_is_positive_but_not_material_event():
    text = "Morgan Stanley raises price target on TechCorp to $300"
    assert _direction(text) == "positive"
    # Sin tipo de evento material: subir un precio objetivo no es earnings,
    # dilución, contrato ni decisión regulatoria de la empresa.
    assert _types(text) == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Strong preorders for the new phone", "positive"),
        ("Preorders strong ahead of Friday launch", "positive"),
        ("Record preorders but valuation concern grows", "mixed"),
        ("Weak preorders point to slowing demand", "negative"),
        ("Company beats estimates and raises guidance", "positive"),
        ("Company misses estimates and cuts guidance", "negative"),
        ("Analysts praise the execution plan", "neutral"),
    ],
)
def test_sentiment_patterns(text, expected):
    assert _direction(text) == expected


def test_phrase_helper_word_edges():
    assert _has_phrase("raises guidance", "raises guidance")
    assert not _has_phrase("praises guidance", "raises guidance")
    assert not _has_phrase("raised his guidance", "raises guidance")
    assert _has_phrase("guía récord: record revenue", "record revenue")


def test_assess_news_scores_celebrity_noise_low():
    from app.core.database import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        assessment = MaterialityService().assess_news(
            db,
            None,
            "Reese Witherspoon launches lifestyle brand",
            "rss_yahoo",
            "https://example.com/celebrity",
            use_jev=False,
        )
        assert assessment.matched_event_types == []
        assert assessment.materiality_score < 7
        assert assessment.requires_update is False
    finally:
        db.close()
