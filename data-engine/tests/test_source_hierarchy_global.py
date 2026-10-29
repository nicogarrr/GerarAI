"""Global-first source classification tests.

The product is global: the owning regulator of the issuer's market is tier 1
whether that is the SEC, CNMV, FCA or another exchange regulator. Spanish
coverage (CNMV) is additive, not the product axis.
"""

from app.services.source_hierarchy_service import (
    SOURCE_TIERS,
    classify_source,
    source_tier_key,
)


def test_cnmv_source_type_is_tier_1_regulatory() -> None:
    assert source_tier_key(source_type="cnmv") == "tier_1_regulatory"


def test_cnmv_url_is_tier_1_regulatory() -> None:
    tier = classify_source(url="https://www.cnmv.es/Portal/Fintech/Fintech.aspx")
    assert tier.key == "tier_1_regulatory"


def test_global_regulator_source_types_are_tier_1() -> None:
    for source_type in ("fca", "bafin", "amf", "consob", "asic", "jfsa", "sedar", "regulator", "exchange_filing"):
        assert source_tier_key(source_type=source_type) == "tier_1_regulatory", source_type


def test_global_regulator_urls_are_tier_1() -> None:
    urls = [
        "https://www.fca.org.uk/publication/final-notices/example.pdf",
        "https://www.bafin.de/SharedDocs/Downloads/example.pdf",
        "https://www.amf-france.org/en/example",
        "https://www.consob.it/web/consob-and-its-activities/example",
        "https://asic.gov.au/regulatory-resources/example",
        "https://www.fsa.go.jp/en/example",
        "https://www.sedar.com/example",
    ]
    for url in urls:
        assert classify_source(url=url).key == "tier_1_regulatory", url


def test_sec_classification_unchanged() -> None:
    assert source_tier_key(source_type="sec_edgar") == "tier_1_regulatory"
    assert classify_source(url="https://www.sec.gov/Archives/edgar/data/1/x.htm").key == "tier_1_regulatory"


def test_tier_1_policy_names_global_regulators() -> None:
    policy = SOURCE_TIERS["tier_1_regulatory"].policy
    assert "SEC" in policy and "CNMV" in policy


def test_data_provider_policy_not_sec_only() -> None:
    policy = SOURCE_TIERS["tier_5_data_provider"].policy
    assert "regulator" in policy


def test_company_ir_and_media_unchanged() -> None:
    assert source_tier_key(source_type="company_ir") == "tier_2_company"
    assert source_tier_key(source_type="reuters") == "tier_4_reputable_media"
    assert source_tier_key(source_type="yahoo") == "tier_5_data_provider"
    assert source_tier_key(source_type="something-else") == "tier_unknown"


def test_domain_suffix_spoof_never_inherits_regulator_trust() -> None:
    """«sec.gov.evil.example» contiene «sec.gov» como subcadena pero no es la SEC.

    Antes de la coincidencia por host, esas URLs heredaban tier_1 (trust 1.0).
    """
    for url in (
        "https://sec.gov.evil.example.com/Archives/x",
        "https://cnmv.es.attacker.io/portal/x",
        "https://reuters.com.evil.io/markets/x",
        "https://notbloomberg.com.evil.example/x",
    ):
        assert classify_source(url=url).key == "tier_unknown", url


def test_short_type_keys_match_full_tokens_only() -> None:
    """«ft» como subcadena clasificaba SoftBank como Financial Times; «amf»
    clasificaba AMFI (India) como AMF (Francia). Solo token completo."""
    assert classify_source(source_type="softbank_holdings").key == "tier_unknown"
    assert classify_source(source_type="amfi_feed").key == "tier_unknown"
    assert classify_source(source_type="ft").key == "tier_4_reputable_media"
    assert classify_source(source_type="amf").key == "tier_1_regulatory"


def test_compound_and_lookalike_type_keys() -> None:
    """Revisión auditor: «asic» por subcadena clasificaba «basic» como tier_1,
    y la regla por longitud dejaba muerta la clave «8-k» (guion).

    Las claves casan como tokens contiguos: «8-k» revive, «basic» y
    «basic_materials» (sector) ya no heredan el tier de ASIC, y las claves
    compuestas reales siguen clasificando igual.
    """
    assert classify_source(source_type="basic").key == "tier_unknown"
    assert classify_source(source_type="basic_materials").key == "tier_unknown"
    assert classify_source(source_type="asic").key == "tier_1_regulatory"
    assert classify_source(source_type="8-k").key == "tier_1_regulatory"
    assert classify_source(source_type="form 8-k/a").key == "tier_1_regulatory"
    assert classify_source(source_type="10-k").key == "tier_1_regulatory"
    assert classify_source(source_type="sec_edgar_daily").key == "tier_1_regulatory"
    assert classify_source(source_type="manual_transcript").key == "tier_3_transcript"


def test_ir_prefix_requires_host_not_substring() -> None:
    """«ir.» como subcadena clasificaba «air.example.com» como fuente primaria."""
    assert classify_source(url="https://air.example.com/news").key == "tier_unknown"
    assert classify_source(url="https://ir.acme.com/investors").key == "tier_2_company"
    assert classify_source(url="https://acme.com/investor-relations").key == "tier_2_company"


def test_stocktwits_social_label_is_tier_8_not_data_provider() -> None:
    # La etiqueta exacta del conector social gana a «stocktwits» a secas
    # (medio agregado vía Google News, que sí es tier 5).
    assert classify_source(source_type="StockTwits (social)").key == "tier_8_social"
    assert classify_source(source_type="Stocktwits").key == "tier_5_data_provider"


def test_social_tier_is_lowest_trust() -> None:
    social = SOURCE_TIERS["tier_8_social"]
    assert social.trust_score < SOURCE_TIERS["tier_unknown"].trust_score
    assert "never" in social.policy.lower()
