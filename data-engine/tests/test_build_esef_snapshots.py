"""ESEF snapshot builder — reviewed-issuer join, latest-per-LEI, honest skips."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from build_esef_snapshots import build, latest_filing_per_lei  # noqa: E402

from app.services.connectors.esef import EsefError, EsefFiling  # noqa: E402


def _filing(lei: str, period_end: str, with_json: bool = True) -> EsefFiling:
    return EsefFiling(
        fxo_id=f"{lei}-{period_end}-ESEF-ES-0",
        lei=lei,
        country="ES",
        period_end=period_end,
        json_url=f"/{lei}/x.json" if with_json else None,
        package_url=f"/{lei}/x.zip",
        sha256="abc",
        error_count=0,
        warning_count=0,
    )


class FakeClient:
    """EsefClient stand-in: no network, canned names/docs."""

    def __init__(self, filings, names, docs):
        self._filings = filings
        self._names = names
        self._docs = docs

    async def list_all_filings(self, country):
        return self._filings

    async def get_entity_name(self, lei):
        name = self._names.get(lei)
        if name is None:
            raise EsefError("unknown LEI")
        return name

    async def fetch_filing_json(self, filing):
        return self._docs[filing.lei]


LEI_ITX = "95980020140005949050"
LEI_UNKNOWN = "95980020140005000000"

DOC = {
    "facts": {
        "fact-1": {
            "value": "1000",
            "decimals": 0,
            "dimensions": {
                "concept": "ifrs-full:Revenue",
                "entity": f"scheme:{LEI_ITX}",
                "period": "2024-02-01T00:00:00/2025-02-01T00:00:00",  # end exclusivo
                "unit": "iso4217:EUR",
            },
        }
    }
}


def test_latest_filing_per_lei_picks_newest_with_json():
    old = _filing(LEI_ITX, "2022-01-31")
    new = _filing(LEI_ITX, "2025-01-31")
    zip_only = _filing(LEI_ITX, "2025-06-30", with_json=False)  # newer but no json
    best = latest_filing_per_lei([new, old, zip_only])
    assert best[LEI_ITX].period_end == "2025-01-31"


def test_latest_filing_per_lei_skips_lei_without_any_json():
    assert latest_filing_per_lei([_filing(LEI_UNKNOWN, "2025-01-31", with_json=False)]) == {}


def test_build_writes_snapshot_only_for_reviewed_issuers(tmp_path):
    asyncio.run(_test_build_writes_snapshot_only_for_reviewed_issuers_impl(tmp_path))


async def _test_build_writes_snapshot_only_for_reviewed_issuers_impl(tmp_path):
    filings = [_filing(LEI_ITX, "2025-01-31"), _filing(LEI_UNKNOWN, "2025-03-31")]
    names = {
        LEI_ITX: "INDUSTRIA DE DISEÑO TEXTIL, S.A.",
        LEI_UNKNOWN: "EMPRESA NO REVISADA, S.A.",
    }
    client = FakeClient(filings, names, {LEI_ITX: DOC})
    manifest = await build(tmp_path, "ES", "2026-09-24", client)

    assert LEI_ITX in manifest["issuers"]
    assert manifest["issuers"][LEI_ITX]["ticker"] == "ITX"
    assert manifest["unresolved"] == {LEI_UNKNOWN: "EMPRESA NO REVISADA, S.A."}

    snap = json.loads((tmp_path / "snapshots" / f"{LEI_ITX}.json").read_text())
    assert snap["ticker"] == "ITX"
    assert snap["period_end"] == "2025-01-31"
    assert snap["fetched_at"] == "2026-09-24"
    rev = snap["facts"]["ifrs-full:Revenue"]["iso4217:EUR"][0]
    assert rev["val"] == "1000"  # string preserved
    assert rev["start"] == "2024-02-01"
    assert (tmp_path / "manifest.json").exists()


def test_build_marks_failed_entity_lookup_unresolved_not_guessed(tmp_path):
    asyncio.run(_test_build_marks_failed_entity_lookup_unresolved_not_guessed_impl(tmp_path))


async def _test_build_marks_failed_entity_lookup_unresolved_not_guessed_impl(tmp_path):
    filings = [_filing(LEI_UNKNOWN, "2025-03-31")]
    client = FakeClient(filings, names={}, docs={})  # lookup fails
    manifest = await build(tmp_path, "ES", "2026-09-24", client)
    assert manifest["issuers"] == {}
    assert manifest["unresolved"][LEI_UNKNOWN] == "<entity lookup failed>"
    assert not list((tmp_path / "snapshots").iterdir()) if (tmp_path / "snapshots").exists() else True


def _doc(revenue_val: str, start: str, end: str, lei: str = LEI_ITX) -> dict:
    return {
        "facts": {
            "fact-1": {
                "value": revenue_val,
                "decimals": 0,
                "dimensions": {
                    "concept": "ifrs-full:Revenue",
                    "entity": f"scheme:{lei}",
                    "period": f"{start}T00:00:00/{end}T00:00:00",
                    "unit": "iso4217:EUR",
                },
            }
        }
    }


def test_filings_per_lei_picks_newest_distinct_periods_up_to_max():
    from build_esef_snapshots import filings_per_lei

    filings = [
        _filing(LEI_ITX, "2024-12-31"),
        _filing(LEI_ITX, "2024-12-31"),  # duplicado de periodo: se ignora
        _filing(LEI_ITX, "2023-12-31"),
        _filing(LEI_ITX, "2022-12-31"),
        _filing(LEI_ITX, "2021-12-31"),
        _filing(LEI_ITX, "2020-12-31"),
        _filing(LEI_ITX, "2019-12-31"),  # fuera con max 5
        _filing(LEI_ITX, "2018-12-31", with_json=False),  # sin json: nunca
    ]
    chosen = filings_per_lei(filings, max_filings=5)[LEI_ITX]
    assert [f.period_end for f in chosen] == [
        "2024-12-31",
        "2023-12-31",
        "2022-12-31",
        "2021-12-31",
        "2020-12-31",
    ]


def test_merge_facts_dedupes_and_newest_filing_wins_restatements():
    from build_esef_snapshots import merge_facts

    from app.services.connectors.esef import normalize_xbrl_json

    newest = normalize_xbrl_json(_doc("1100", "2024-01-01", "2025-01-01"))
    older = normalize_xbrl_json(_doc("1000", "2024-01-01", "2025-01-01"))
    older_year = normalize_xbrl_json(_doc("900", "2023-01-01", "2024-01-01"))
    merged = merge_facts([newest, older, older_year])
    entries = merged["ifrs-full:Revenue"]["iso4217:EUR"]
    assert len(entries) == 2
    by_end = {e["end"]: e["val"] for e in entries}
    assert by_end["2024-12-31"] == "1100"  # reexpresion del filing reciente
    assert by_end["2023-12-31"] == "900"


def test_build_merges_multiple_filings_into_one_snapshot(tmp_path):
    class MultiDocClient(FakeClient):
        async def fetch_filing_json(self, filing):
            docs = {
                "2024-12-31": _doc("1100", "2024-01-01", "2025-01-01"),
                "2023-12-31": _doc("900", "2023-01-01", "2024-01-01"),
            }
            return docs[filing.period_end]

    filings = [_filing(LEI_ITX, "2024-12-31"), _filing(LEI_ITX, "2023-12-31")]
    client = MultiDocClient(filings, {LEI_ITX: "INDUSTRIA DE DISEÑO TEXTIL, S.A."}, {})
    manifest = asyncio.run(build(tmp_path, "ES", "2026-09-25", client))
    entry = manifest["issuers"][LEI_ITX]
    assert entry["periods"] == ["2024-12-31", "2023-12-31"]
    snapshot = json.loads((tmp_path / "snapshots" / f"{LEI_ITX}.json").read_text())
    entries = snapshot["facts"]["ifrs-full:Revenue"]["iso4217:EUR"]
    assert {e["end"] for e in entries} == {"2024-12-31", "2023-12-31"}


def test_merge_facts_preserves_multiple_instant_years():
    """Balance (instant): cada ejercicio es un instant distinto y debe
    sobrevivir al merge; el bug colapsaba todos los instantes en uno."""
    from build_esef_snapshots import merge_facts

    newest = {"ifrs-full:Assets": {"iso4217:EUR": [
        {"instant": "2024-12-31", "val": "100"},
        {"instant": "2023-12-31", "val": "95"},
    ]}}
    older = {"ifrs-full:Assets": {"iso4217:EUR": [
        {"instant": "2023-12-31", "val": "94"},  # reexpresion: gana newest (95)
        {"instant": "2022-12-31", "val": "90"},
    ]}}
    merged = merge_facts([newest, older])
    entries = merged["ifrs-full:Assets"]["iso4217:EUR"]
    by_instant = {e["instant"]: e["val"] for e in entries}
    assert by_instant == {"2024-12-31": "100", "2023-12-31": "95", "2022-12-31": "90"}
