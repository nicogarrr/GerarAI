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


@pytest.mark.parametrize(
    "text,expected",
    [
        # Auditoría prod 28-oct-2026: titulares reales que salían «neutral».
        ("Scotiabank Upgrades AST SpaceMobile to Sector Outperform From Sector Perform", "positive"),
        ("AST SpaceMobile Stock Is Gaining Monday: What's Going On?", "positive"),
        ("Alibaba Won A Pentagon Injunction", "positive"),
        ("Intuitive Machines Surges 9% as Small-Cap Space Selloff Reverses; Rocket Lab Climbs 7%", "mixed"),
        ("Las acciones de AST SpaceMobile suben tras la mejora de recomendación", "positive"),
        ("Alibaba shares tumble as China presses e-commerce platforms", "negative"),
        ("Alibaba Shares Post Steepest Drop in Two Months on China Curbs", "negative"),
        ("Morgan Stanley Sees More Downside In Chinese Stocks", "negative"),
        ("Alibaba Stock Slips as China Renews Regulatory Scrutiny", "negative"),
        ("AST SpaceMobile Stock Under Pressure: SpaceX Competition, ViaSat Dispute", "negative"),
        ("Rocket Lab Just Dropped 29% in a Month", "negative"),
        ("AST SpaceMobile Stock Falls 1.8% - Here's What Happened", "negative"),
        ("Alibaba cae un 5% tras nuevas restricciones", "negative"),
        # Controles que no deben moverse.
        ("Analysts praise the execution plan", "neutral"),
        ("BlackRock's stake includes sole voting power over 14.9M shares", "neutral"),
        ("New iPhone expected this fall", "neutral"),
        ("Company beats estimates and raises guidance", "positive"),
        ("Company misses estimates and cuts guidance", "negative"),
    ],
)
def test_market_verbs_and_spanish_direction(text, expected):
    assert _direction(text) == expected


def test_social_source_materiality_is_capped():
    # Un mensaje social con término crítico («bankruptcy») nunca es material:
    # techo duro por debajo del umbral de revisión (7).
    assessment = MaterialityService().assess_news(
        None,
        None,
        "$ACME bankruptcy filing imminent, trust me",
        "StockTwits (social)",
        "https://stocktwits.com/user/message/1",
    )
    assert assessment.source_tier == "tier_8_social"
    assert assessment.materiality_score <= 2
    assert assessment.requires_update is False
