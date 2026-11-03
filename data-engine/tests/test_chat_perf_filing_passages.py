"""Rendimiento de los pasajes de filings del chat: mismos pasajes, menos trabajo.

La subcadena descarta antes de la expresión regular y la ventana de 400
caracteres se calcula con dos punteros. Se comprueba que el resultado es el
mismo que el del algoritmo anterior (referencia ingenua copiada aquí).
"""

from __future__ import annotations

import random

from app.services.filing_passages import _best_window, _term_re


def _naive_window(hits, idf, span=400):
    best = 0.0
    for pos, _ in hits:
        window = {t for p, t in hits if pos <= p < pos + span}
        best = max(best, sum(idf[t] for t in window))
    return best


def test_best_window_matches_naive_on_random_hits():
    rng = random.Random(4)
    terms = ["risk", "debt", "margin", "operating income", "employees"]
    for _ in range(2000):
        hits = sorted((rng.randint(0, 3000), rng.choice(terms)) for _ in range(rng.randint(0, 40)))
        idf = {t: rng.uniform(0.1, 3.0) for t in terms}
        assert _best_window(hits, idf) == _naive_window(hits, idf)


def test_best_window_ties_on_same_position_and_edges():
    idf = {"a": 1.0, "b": 2.0, "c": 4.0}
    hits = [(0, "a"), (0, "b"), (399, "c"), (400, "a"), (800, "c")]
    assert _best_window(hits, idf) == _naive_window(hits, idf) == 7.0
    assert _best_window([], idf) == 0.0


def test_substring_is_necessary_for_the_term_regex():
    # Base de la criba: si la expresión casa, el término (minúsculas, espacios
    # simples) está como subcadena del texto normalizado.
    rng = random.Random(9)
    vocab = ["risk", "risks", "riskier", "s&p", "500", "operating", "income", "debt.", "EmployeeStockMember", "employee"]
    terms = ["risk", "s&p 500", "operating income", "debt", "employee", "employees"]
    for _ in range(3000):
        text = " ".join(rng.choice(vocab) for _ in range(rng.randint(1, 30)))
        low = " ".join(text.lower().split())
        for term in terms:
            if _term_re(term).search(low):
                assert " ".join(term.lower().split()) in low
