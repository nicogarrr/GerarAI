"""Listing venue is not the issuer's legal jurisdiction (e.g. ERF.PA in LU)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services import esef_live

LEI = "529900JEHFM47DYY3S57"


def row(lei=LEI, name="EUROFINS SCIENTIFIC SE", country="LU", status="ISSUED"):
    return {"attributes": {"lei": lei, "entity": {"legalName": {"name": name}, "jurisdiction": country},
                           "registration": {"status": status}}}


def resolve(monkeypatch, global_rows, *, local_rows=None, name="Eurofins Scientific SE", has_filings=True, isin=None):
    calls = []

    async def gleif(http, params):
        calls.append(params.copy())
        if "filter[entity.jurisdiction]" in params:
            return local_rows or []
        return global_rows

    monkeypatch.setattr(esef_live, "gleif_lei_records", gleif)
    esef = SimpleNamespace(list_filings_for_lei=AsyncMock(return_value=[object()] if has_filings else []))
    company = SimpleNamespace(ticker="ERF.PA", name=name, isin=isin)

    async def run():
        async with httpx.AsyncClient() as http:
            return await esef_live.resolve_issuer(company, esef=esef, http=http)

    return asyncio.run(run()), calls, esef


def test_foreign_domiciled_issuer_resolves_only_by_exact_legal_name(monkeypatch):
    (identity, reason), calls, _ = resolve(monkeypatch, [row()])
    assert reason == "ok"
    assert identity.lei == LEI
    assert identity.method == "name_gleif_cross_border"
    assert calls[0]["filter[entity.jurisdiction]"] == "FR"
    assert "filter[entity.jurisdiction]" not in calls[1]
    assert calls[1]["filter[entity.legalName]"] == "Eurofins Scientific SE"
    assert "filter[fulltext]" not in calls[1]


@pytest.mark.parametrize("name", ["Eurofins Scientific", "Eurofins", "Scientific Eurofins SE"])
def test_cross_border_search_does_not_accept_partial_or_reordered_names(monkeypatch, name):
    (identity, _), _, _ = resolve(monkeypatch, [row()], name=name)
    assert identity is None


def test_cross_border_homonyms_remain_ambiguous(monkeypatch):
    (identity, reason), _, _ = resolve(monkeypatch, [row(), row(lei="OTHERLEI", country="BE")])
    assert identity is None
    assert reason.startswith("nombre_ambiguo")


@pytest.mark.parametrize("status", ["RETIRED", "ANNULLED", "DUPLICATE"])
def test_inactive_global_record_is_not_selected(monkeypatch, status):
    (identity, _), _, _ = resolve(monkeypatch, [row(status=status)])
    assert identity is None


def test_exact_name_without_filings_is_not_enough(monkeypatch):
    (identity, _), _, _ = resolve(monkeypatch, [row()], has_filings=False)
    assert identity is None


def test_existing_jurisdiction_match_keeps_single_request(monkeypatch):
    (identity, reason), calls, _ = resolve(monkeypatch, [], local_rows=[row(country="FR")])
    assert reason == "ok" and identity.method == "name_gleif"
    assert len(calls) == 1


def test_full_global_page_is_not_treated_as_unique(monkeypatch):
    (identity, reason), _, _ = resolve(monkeypatch, [row()] * 10)
    assert identity is None
    assert reason.startswith("nombre_ambiguo")


def test_legal_name_punctuation_and_case_are_normalized(monkeypatch):
    (identity, reason), _, _ = resolve(monkeypatch, [row()], name=" eurofins scientific S.E. ")
    assert reason == "ok" and identity.lei == LEI


def test_global_lookup_failure_is_reported_not_guessed(monkeypatch):
    async def failing(http, params):
        if "filter[entity.jurisdiction]" in params:
            return []
        raise httpx.ConnectError("offline")

    async def run():
        async with httpx.AsyncClient() as http:
            return await esef_live.resolve_issuer(
                SimpleNamespace(ticker="ERF.PA", name="Eurofins Scientific SE", isin=None),
                esef=SimpleNamespace(list_filings_for_lei=AsyncMock()), http=http,
            )

    monkeypatch.setattr(esef_live, "gleif_lei_records", failing)
    identity, reason = asyncio.run(run())
    assert identity is None and reason == "gleif_error: ConnectError"
