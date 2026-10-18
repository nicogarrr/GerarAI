"""«Qué ha cambiado»: sin spam de despachos, sin tarjetas sin relación, sin duplicados."""
from types import SimpleNamespace

from app.api.routes.memory import _visible_thesis_changes


def change(summary, *, claims=None, metrics=None):
    return SimpleNamespace(
        summary=summary,
        affected_claim_ids=claims or [],
        affected_metrics=metrics or [],
    )


def test_law_firm_solicitation_hidden():
    rows = [
        change("Rosen Law Firm reminds investors who lost money of the lead plaintiff deadline in the securities class action.", metrics=["regulatory_risk"]),
        change("MSFT cuts guidance after earnings miss.", metrics=["guidance"]),
    ]
    visible = _visible_thesis_changes(rows, 50)
    assert len(visible) == 1 and "guidance" in visible[0].summary


def test_no_reliable_relation_hidden():
    rows = [
        change("No structural thesis node matched with sufficient confidence. Reese Witherspoon vende su marca.", metrics=["regulatory_risk"]),
        change("No stored thesis is available for semantic impact mapping. Morgan Stanley sube.", metrics=["guidance"]),
        change("Sin relacion con nada persistido.", claims=[], metrics=[]),
        change("MSFT wins major contract.", claims=[12]),
    ]
    visible = _visible_thesis_changes(rows, 50)
    assert len(visible) == 1 and "contract" in visible[0].summary


def test_duplicate_summaries_shown_once():
    rows = [
        change("MSFT cuts guidance after earnings miss!", metrics=["guidance"]),
        change("msft cuts guidance after earnings miss.", metrics=["guidance"]),
        change("MSFT wins major customer contract.", metrics=["backlog_conversion"]),
    ]
    visible = _visible_thesis_changes(rows, 50)
    assert len(visible) == 2
    assert "cuts" in visible[0].summary  # se conserva la más reciente (primera)


def test_limit_applies_after_filtering():
    rows = [
        change("Rosen Law Firm reminds investors who lost money of the lead plaintiff deadline."),
        change("Cambio real uno.", metrics=["guidance"]),
        change("Cambio real dos.", metrics=["guidance"]),
    ]
    visible = _visible_thesis_changes(rows, 2)
    assert len(visible) == 2


def test_claims_or_metrics_any_relation_counts():
    rows = [change("Solo métricas.", metrics=["guidance"]), change("Solo afirmaciones.", claims=[5])]
    assert len(_visible_thesis_changes(rows, 50)) == 2
