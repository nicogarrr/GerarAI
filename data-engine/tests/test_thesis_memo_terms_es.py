"""Términos internos que se colaban en inglés (o como código) en el memo.

Visto en una prueba real (ASTS y BABA, 2026-10-27):
- «se sigue como ... con el modelo probability weighted scenarios+dilution» y
  «sotp+buyback adjusted dcf»: las claves compuestas con «+» no se traducían;
- «Motor: holding company», riesgos «dilution, spectrum, execution, funding»;
- «Versión del modelo fundamental usada en esta corrida: `None`»;
- «Pregunta primaria: ¿Pueden ... ingresos.» (se abría «¿» y se cerraba con punto);
- «Transcripción: ... disponible..» (doble punto).
"""

from app.models import Company
from app.services.memo_text_es import term_es
from app.services.thesis_service import ThesisService


def test_term_es_traduce_claves_compuestas_con_mas():
    assert term_es("probability weighted scenarios+dilution") == (
        "Escenarios ponderados por probabilidad + dilución"
    )
    assert term_es("sotp+buyback adjusted dcf") == "suma de partes (SOTP) + DCF ajustado por recompras"


def test_term_es_motores_y_riesgos_frecuentes():
    assert term_es("holding company") == "holding"
    assert term_es("china adr holding") == "holding china cotizada como ADR"
    assert term_es("space network") == "red espacial"
    assert [term_es(r) for r in ("dilution", "spectrum", "execution", "funding")] == [
        "dilución",
        "espectro",
        "ejecución",
        "financiación",
    ]


def _render(**company_overrides) -> str:
    fields = dict(
        ticker="ASTS",
        name="AST SpaceMobile",
        exchange="NASDAQ",
        currency="USD",
        sector="Communication Services",
        industry="Satellite telecom",
        company_type="space_telecom_pre_fcf",
        valuation_model="probability weighted scenarios+dilution",
        special_sources=["SEC", "FCC"],
        special_risks=["dilution", "spectrum", "execution", "funding"],
        factor_tags=[],
    )
    fields.update(company_overrides)
    return ThesisService()._render_markdown(
        Company(**fields),
        {},
        {"passed": True, "source_coverage_score": 100, "unsupported_claims": 0},
        {},
        long_term_model={"status": "missing_mandatory_drivers", "persistence": {"version": None}},
        version=1,
        hypothesis="Hipótesis de prueba.",
        catalysts=[],
        invalidation_criteria=["Un criterio."],
        scenario_probabilities=None,
    )


def test_memo_sin_claves_inglesas_ni_none():
    md = _render()
    assert "probability weighted" not in md
    assert "+dilution" not in md
    assert "Escenarios ponderados por probabilidad + dilución" in md
    assert "dilution, spectrum" not in md
    assert "dilución, espectro, ejecución, financiación" in md
    assert "usada en esta corrida: `None`" not in md
    assert "sin versión persistida" in md


def test_pregunta_primaria_cierra_con_interrogacion():
    md = _render(company_type="standard", valuation_model="standard_dcf")
    line = next(ln for ln in md.splitlines() if "Pregunta primaria:" in ln)
    if "¿" in line:
        assert line.rstrip().endswith("?"), line
        assert not line.rstrip().endswith("?."), line
