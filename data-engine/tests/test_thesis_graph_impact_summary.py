"""Copy del impacto semántico de una noticia (QA 21-oct-2026).

La forma antigua «Afecta a 0 afirmaciones y nodos de la tesis: …» se leía
como si nada estuviera afectado pese a listar apartados. El texto nuevo
distingue 0 afirmaciones con apartados afectados y usa la forma que el
frontend (change-copy.ts) reconoce para traducir las etiquetas.
"""

from app.services.thesis_graph_service import impact_summary_text


def test_cero_afirmaciones_con_apartados_es_honesto():
    text = impact_summary_text(0, ["Technology", "Funding"])
    assert text == (
        "No afecta a ninguna afirmación concreta; toca estos apartados de la tesis: "
        "Technology, Funding."
    )
    assert "0 afirmaciones" not in text


def test_con_afirmaciones_usa_la_forma_reconocida_por_el_frontend():
    text = impact_summary_text(2, ["Regulatory"])
    assert text == "Afecta a 2 afirmaciones y a estos apartados de la tesis: Regulatory."


def test_sin_apartados_ni_afirmaciones_no_inventa_impacto():
    assert impact_summary_text(0, []) == (
        "Ningún nodo estructural de la tesis coincide con confianza suficiente."
    )
