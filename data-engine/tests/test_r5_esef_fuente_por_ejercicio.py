"""A package list is not exact fact provenance, even if its dates overlap."""
from datetime import date

from app.models import Document, FinancialFact

LEI = "MINO79WLOO247M1IL051"


def _src(year: int, origin: str = "filings.xbrl.org") -> dict:
    return {"period_end": f"{year}-12-31", "origin": origin,
            "url": f"https://filings.xbrl.org/{LEI}/{year}-12-31/ESEF/NL/0/{LEI}-{year}-12-31-en.json",
            "fxo_id": f"{LEI}-{year}-12-31-ESEF-NL-0", "sha256": "ab" * 32}


def _doc(sources: list[dict] | None, url: str | None = None) -> Document:
    meta = {"provider": "ESEF", "normalized": True}
    if sources is not None:
        meta["filing_sources"] = sources
    return Document(title="ESEF XBRL facts - AIR.PA", source_type="ESEF", source_url=url, metadata_=meta)


def _fact(period: str, doc: Document) -> FinancialFact:
    fact = FinancialFact(metric="net_income", value=1, unit="EUR", period=period, fiscal_quarter="FY")
    fact.source = doc
    return fact


def test_filing_dates_do_not_prove_which_package_supplied_a_fact():
    doc = _doc([_src(2025), _src(2024), _src(2023)])
    for year in range(2021, 2026):
        assert _fact(f"{year}-12-31:FY", doc).source_url is None


def test_matching_fca_period_does_not_prove_fact_provenance():
    nsm = {"period_end": "2025-12-31", "origin": "fca_nsm",
           "url": "https://data.fca.org.uk/artefacts/NSM/RNS/abc.zip", "sha256": "cd" * 32}
    assert _fact("2025-12-31:FY", _doc([nsm])).source_url is None


def test_unit_metric_and_period_are_not_recoverable_from_package_metadata():
    doc = _doc([_src(2025)])
    for unit in ("EUR", "USD", "shares"):
        for metric in ("net_income", "total_assets", "revenue"):
            fact = _fact("2024-12-31:FY", doc)
            fact.unit, fact.metric = unit, metric
            assert fact.source_url is None


def test_sin_informes_o_enlace_no_https_sigue_sin_fuente():
    assert _fact("2025-12-31:FY", _doc(None)).source_url is None
    assert _fact("2025-12-31:FY", _doc([])).source_url is None
    bad = {**_src(2025), "url": "filings.xbrl.org/api/filings (fxo_id=x)"}
    assert _fact("2025-12-31:FY", _doc([bad])).source_url is None
    assert _fact("2025-12-31:FY", _doc([{"period_end": "basura", "url": _src(2025)["url"]}])).source_url is None
    assert _fact("sin-fecha", _doc([_src(2025)])).source_url is None


def test_url_guardada_del_documento_manda():
    real = "https://www.sec.gov/Archives/edgar/data/1/000000000125000001/x.htm"
    assert _fact("2025-12-31:FY", _doc([_src(2025)], url=real)).source_url == real


def test_health_does_not_score_facts_with_unverified_sources():
    """No score is better than a score built on an invented citation."""
    from app.services.financial_health import HealthFact, calculate_health

    doc = _doc([_src(2025), _src(2024), _src(2023)])
    values = {
        2023: {"total_assets": 100},
        2024: {"total_assets": 110, "net_income": 5, "long_term_debt": 30, "current_assets": 50,
               "current_liabilities": 30, "gross_profit": 30, "revenue": 100},
        2025: {"total_assets": 120, "net_income": 12, "long_term_debt": 20, "operating_cash_flow": 15,
               "current_assets": 70, "current_liabilities": 30, "gross_profit": 44, "revenue": 130,
               "common_stock_issued": 0},
    }
    facts = []
    for year, metrics in values.items():
        for metric, value in metrics.items():
            url = _fact(f"{year}-12-31:FY", doc).source_url
            facts.append(HealthFact(len(facts) + 1, metric, year, value, "EUR", date(year, 12, 31),
                                    url or "", "ESEF", 1))
    out = calculate_health(facts, sector="Industrials", company_type="operating", today=date(2026, 11, 11))
    assert out.get("reason") == "Sin ejercicios anuales con fuente"
    assert out["piotroski"]["score"] is None
