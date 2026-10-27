"""Name matching stays live per invocation; caches contain only bounded text."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.models.entities import Company
from app.services import company_names as names


def company(id, name, ticker="TEST"):
    return Company(id=id, ticker=ticker, name=name)


@pytest.mark.parametrize("suffix", ["S.A.", "S.A", "S. A.", "S.L.", "S.L", "S. L.", "S.P.A.", "N.V.", "L.L.C.", "L.P.", "S.A. ADR", "S.A. S.L."])
def test_dotted_terminal_legal_suffixes(suffix):
    c = company(1, f"Banco Santander, {suffix}", "SAN")
    assert names.core_name(c.name) == ["banco", "santander"]
    matched = names.companies_named_in("¿Cómo va Banco Santander?", [c])
    assert matched.companies == [c]
    assert matched.covers(9, 24)


@pytest.mark.parametrize("name,expected", [
    ("Industria S", ["industria", "s"]),
    ("Industria L", ["industria", "l"]),
    ("Banco S.A. Servicios", ["banco", "s", "a", "servicios"]),
    ("Algoma Steel Group Inc.", ["algoma", "steel"]),
    ("Sage", ["sage"]),
    ("Santander", ["santander"]),
])
def test_no_blind_letter_or_interior_suffix_removal(name, expected):
    assert names.core_name(name) == expected


@pytest.mark.parametrize("question", ["Brookfield", "Brookfield Corporation"])
def test_ambiguous_brookfield_is_not_chosen(question):
    cs = [company(1, "Brookfield Corporation", "BN"), company(2, "Brookfield Renewable Partners", "BEP")]
    matched = names.companies_named_in(question, cs)
    assert not matched.companies
    assert matched.ambiguous == [("Brookfield", cs)]
    assert "BN" in names.ambiguous_name_answer(*matched.ambiguous[0])
    assert "BEP" in names.ambiguous_name_answer(*matched.ambiguous[0])


@pytest.mark.parametrize("question", ["mi meta de ahorro", "Meta", "Visa", "Target", "necesito una visa"])
def test_generic_first_words_do_not_become_companies(question):
    cs = [company(1, "Meta Platforms Inc."), company(2, "Visa Inc."), company(3, "Target Corporation")]
    result = names.companies_named_in(question, cs)
    assert not result.companies and not result.ambiguous


def test_caches_do_not_retain_company_results_or_stale_names():
    original = company(1, "Apple Inc.", "AAPL")
    assert names.companies_named_in("Apple", [original]).companies == [original]
    original.name = "Banco Santander S.A."
    assert not names.companies_named_in("Apple", [original]).companies
    assert names.companies_named_in("Banco Santander", [original]).companies == [original]
    replacement = company(1, "Apple Inc.", "OTHER")
    assert names.companies_named_in("Apple", [replacement]).companies == [replacement]
    assert not names.companies_named_in("Apple", []).companies
    assert names.companies_named_in("Apple", (c for c in [replacement])).companies == [replacement]
    # Mutating the public list must not mutate the cached tuple.
    words = names.core_name("Banco Santander S.A.")
    words.clear()
    assert names.core_name("Banco Santander S.A.") == ["banco", "santander"]


def test_prefilter_preserves_case_accents_punctuation_boundaries_and_ampersand():
    cs = [company(1, "Crédit Agricole S.A."), company(2, "Smith & Wesson Inc."), company(3, "Apple Inc.")]
    q = "crédit-agricole y Smith & Wesson y Apple"
    result = names.companies_named_in(q, cs)
    assert result.companies == cs
    assert [q[s:e] for s, e in result.spans] == ["crédit-agricole", "Smith & Wesson", "Apple"]
    assert not names.companies_named_in("Pineapple y apple", cs).companies


def test_unmentioned_names_do_not_compile_per_company(monkeypatch):
    if hasattr(names, "_cached_phrase_re"):
        names._cached_phrase_re.cache_clear()
    cs = [company(i, f"Synthetic{i} Business{i} Inc.") for i in range(2116)]
    calls = []
    original = names.re.compile

    def counted(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(names.re, "compile", counted)
    assert not names.companies_named_in("¿Cómo va mi cartera?", cs).companies
    assert calls == []


def test_cache_sizes_are_bounded():
    for i in range(8300):
        names._core_words(f"Synthetic{i} Business{i}")
    for i in range(4200):
        names._phrase_re([f"synthetic{i}"])
    assert names._core_words.cache_info().currsize == 8192
    assert names._cached_phrase_re.cache_info().currsize == 4096


def test_concurrent_calls_return_only_the_current_call_objects():
    # Same names and ids but different object identities simulate independent
    # sessions. Even a cache hit must return this call's objects only.
    def check(i):
        current = company(1, "Banco Santander S.A.", f"SAN{i}")
        result = names.companies_named_in("¿Cómo va Banco Santander?", [current])
        return result.companies == [current] and result.companies[0] is current

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(check, range(100)))
