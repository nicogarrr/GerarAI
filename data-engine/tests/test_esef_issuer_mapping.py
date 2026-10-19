"""Mapping reviewed ESEF no-ES (NL: ASML) y build multi-pais."""

import json

from app.services.esef_issuer_mapping import (
    REVIEWED_ISSUERS_NL,
    resolve_issuer_nl,
    resolve_ticker_for_country,
    reviewed_tickers,
)


def test_asml_resolves_by_legal_name_ticker_isin_and_lei():
    assert resolve_issuer_nl("ASML Holding N.V.").ticker == "ASML"
    assert resolve_issuer_nl("asml").ticker == "ASML"
    assert resolve_issuer_nl("NL0010273215").ticker == "ASML"
    assert resolve_issuer_nl("724500Y6DUVHQD6OXN27").ticker == "ASML"


def test_unknown_never_guessed():
    assert resolve_issuer_nl("") is None
    assert resolve_issuer_nl("Koninklijke Philips N.V.") is None
    assert resolve_issuer_nl("ASML Holding") is None  # parcial: no se adivina


def test_country_routing():
    assert resolve_ticker_for_country("NL", "ASML Holding N.V.") == "ASML"
    assert resolve_ticker_for_country("ES", "AENA, S.M.E., S.A.") == "AENA"
    assert resolve_ticker_for_country("FR", "ASML Holding N.V.") is None
    assert "ASML" in reviewed_tickers() and "AENA" in reviewed_tickers()


def test_multi_country_build_merges_one_manifest(tmp_path):
    """ES + NL acaban en un solo manifest; antes el segundo pais pisaba al
    primero y AENA desaparecia del indice de snapshots."""
    import asyncio
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from build_esef_snapshots import build

    from app.services.connectors.esef import EsefFiling

    aena_lei = "959800R7QMXKF0NFMT29"
    asml_lei = REVIEWED_ISSUERS_NL[0].lei

    def filing(lei, country):
        return EsefFiling(
            fxo_id=f"{lei}-2024-12-31-ESEF-{country}-0", lei=lei,
            country=country, period_end="2024-12-31",
            json_url=f"/{lei}/2024-12-31/ESEF/{country}/0/x.json",
            package_url=None, sha256="abc",
            error_count=0, warning_count=0,
        )

    class FakeClient:
        async def list_all_filings(self, country, page_size=200):
            return [filing(aena_lei if country == "ES" else asml_lei, country)]

        async def get_entity_name(self, lei):
            return {aena_lei: "AENA, S.M.E., S.A.",
                    asml_lei: "ASML Holding N.V."}[lei]

        async def fetch_filing_json(self, filing_):
            return {"facts": {}}

    manifest = asyncio.run(
        build(tmp_path, ["ES", "NL"], "2026-10-19", FakeClient()))
    assert set(manifest["issuers"].keys()) == {aena_lei, asml_lei}
    assert manifest["issuers"][asml_lei]["ticker"] == "ASML"
    assert manifest["countries"] == ["ES", "NL"]
    on_disk = json.loads((tmp_path / "manifest.json").read_text())
    assert set(on_disk["issuers"].keys()) == {aena_lei, asml_lei}
    assert (tmp_path / "snapshots" / f"{asml_lei}.json").exists()


def test_kerry_ie_resolves_and_never_guessed():
    from app.services.esef_issuer_mapping import (
        resolve_issuer_by_lei,
        resolve_issuer_ie,
    )

    assert resolve_issuer_ie("Kerry Group Public Limited Company").ticker == "KRKNF"
    assert resolve_issuer_ie("Kerry Group plc").ticker == "KRKNF"
    assert resolve_issuer_ie("IE0004906560").ticker == "KRKNF"
    assert resolve_issuer_ie("635400TLVVBNXLFHWC59").ticker == "KRKNF"
    assert resolve_issuer_ie("KYGA").ticker == "KRKNF"
    assert resolve_issuer_ie("") is None
    assert resolve_issuer_ie("Kerry") is None  # parcial: no se adivina
    assert resolve_issuer_by_lei("635400TLVVBNXLFHWC59").ticker == "KRKNF"
    assert resolve_issuer_by_lei("724500Y6DUVHQD6OXN27").ticker == "ASML"
    assert resolve_issuer_by_lei("") is None
    assert resolve_ticker_for_country("IE", "Kerry Group plc") == "KRKNF"
    assert "KRKNF" in reviewed_tickers()
