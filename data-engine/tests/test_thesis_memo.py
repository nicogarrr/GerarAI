"""Thesis memo (downloadable Markdown) contract tests.

The memo is the professional thesis deliverable: it must render every
persisted section verbatim, mark anything missing as "pendiente" (never
fabricate), and always close with the not-financial-advice disclaimer.
"""

import re
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    Claim,
    ClaimEvidence,
    Company,
    SourceAudit,
    ThesisSection,
    ThesisVersion,
)
from app.services.thesis_memo import build_memo_markdown


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    from app.models import FundamentalModelVersion

    db.add(FundamentalModelVersion(
        company_id=company.id, version=1, engine_version="test", algorithm_version="test",
        framework_key="dcf", horizon_years=10, status="ok", publishable=True,
        input_fingerprint="input", forecast_fingerprint="forecast",
        market_snapshot_fingerprint="market", valuation_snapshot_fingerprint="valuation",
    ))
    db.commit()
    return company


def _full_thesis(db: Session, company_id: int) -> ThesisVersion:
    thesis = ThesisVersion(
        company_id=company_id, version=2, status="published", rating="buy",
        thesis_markdown="# t", executive_summary="Servicios y ecosistema sostienen el crecimiento.",
        hypothesis="La base instalada monetiza servicios a doble digito.",
        current_price=200, bear_value=150, base_value=220, bull_value=300,
        expected_value=235, margin_of_safety=0.15,
        # Fracciones persistidas por el motor (la ficha las lee con formatPercent fromRatio).
        scenario_probabilities={"bear": 0.20, "base": 0.55, "bull": 0.25},
        catalysts=[
            {"label": "Próximos resultados", "date": "2026-11-05"},
            {"title": "Resultados Q4", "date": "2026-10-30"},
            "Ciclo de renovacion de iPhone",
        ],
        invalidation_criteria=["Crecimiento de servicios < 5%", "Margen bruto < 40%"],
        data_confidence_score=82, source_coverage_score=74,
        red_team_score=61, valuation_risk_score=35,
        input_fingerprint="fp-abc123",
    )
    db.add(thesis)
    db.flush()
    db.add(ThesisSection(
        thesis_version_id=thesis.id, company_id=company_id,
        section_key="moat", title="Foso competitivo", body="Ecosistema cerrado.", order_index=1,
    ))
    db.add(ThesisSection(
        thesis_version_id=thesis.id, company_id=company_id,
        section_key="risks", title="Riesgos", body="Regulacion App Store.", order_index=2,
    ))
    claim = Claim(company_id=company_id, thesis_version_id=thesis.id,
                  statement="Servicios crecen a doble digito interanual")
    db.add(claim)
    db.flush()
    db.add(ClaimEvidence(
        claim_id=claim.id, source_url="https://www.sec.gov/Archives/example",
        summary="10-K services revenue", source_tier="primary",
    ))
    db.commit()
    return thesis


def test_full_thesis_renders_every_section(db):
    company = _company(db)
    thesis = _full_thesis(db, company.id)
    memo = build_memo_markdown(db, company, thesis)

    assert memo.startswith("# Memo de tesis — AAPL (Apple)")
    assert "Versión 2 · estado publicada · rating compra" in memo
    assert "La base instalada monetiza servicios a doble digito." in memo
    # Valuation table: money formatting + probabilities.
    assert "| Bajista | $150.00 | 20 % |" in memo
    assert "| Base | $220.00 | 55 % |" in memo
    assert "| Alcista | $300.00 | 25 % |" in memo
    assert "Precio del modelo: $200.00 · Valor esperado: $235.00 · Margen de seguridad: 15,0 %" in memo
    # Catalysts: dict form renders title + date; string form renders verbatim.
    assert "- Próximos resultados (2026-11-05)" in memo
    assert "- Resultados Q4 (2026-10-30)" in memo
    # El dict crudo de Python no puede aparecer jamas en el documento.
    assert "{'label'" not in memo
    assert "- Ciclo de renovacion de iPhone" in memo
    assert "- Crecimiento de servicios < 5%" in memo
    # Evidence quality scores.
    assert "Confianza de datos 82/100 · cobertura de fuentes 74/100 · red-team 61/100 · riesgo de valoración 35/100" in memo
    # Custom sections in order.
    assert memo.index("### Foso competitivo") < memo.index("### Riesgos")
    assert "Ecosistema cerrado." in memo
    # Sources with tier + url.
    assert "[primary] Servicios crecen a doble digito interanual — https://www.sec.gov/Archives/example" in memo
    # Footer + disclaimer always close the memo.
    assert "fingerprint fp-abc123" in memo
    assert memo.rstrip().endswith(
        "Documento informativo de investigación. NO es asesoramiento financiero "
        "ni recomendación de compra o venta."
    )


def test_sparse_thesis_marks_everything_pendiente_never_fabricates(db):
    company = _company(db)
    thesis = ThesisVersion(
        company_id=company.id, version=1, status="draft", rating="watch",
        thesis_markdown="# t", executive_summary="",
    )
    db.add(thesis)
    db.commit()
    memo = build_memo_markdown(db, company, thesis)

    assert "| Bajista | pendiente | pendiente |" in memo
    assert "Margen de seguridad: pendiente" in memo
    assert memo.count("_Pendiente._") >= 3  # hipotesis, resumen, catalizadores, invalidacion
    assert "## Fuentes" not in memo  # no persisted evidence: section omitted, not invented
    assert "fingerprint n/a" in memo
    assert "NO es asesoramiento financiero" in memo


def test_stale_flag_warns_with_latest_data_date(db):
    company = _company(db)
    thesis = ThesisVersion(
        company_id=company.id, version=1, status="published", rating="watch",
        thesis_markdown="# t", executive_summary="s",
    )
    db.add(thesis)
    db.commit()
    memo = build_memo_markdown(
        db, company, thesis, stale=True, latest_data_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    assert "DESACTUALIZADA" in memo
    assert "hasta 20 sept 2026" in memo


def test_stale_flag_without_date_is_honest_unknown(db):
    company = _company(db)
    thesis = ThesisVersion(
        company_id=company.id, version=1, status="published", rating="watch",
        thesis_markdown="# t", executive_summary="s",
    )
    db.add(thesis)
    db.commit()
    memo = build_memo_markdown(db, company, thesis, stale=True, latest_data_at=None)
    assert "hasta desconocida" in memo


def test_evidence_without_url_is_excluded(db):
    company = _company(db)
    thesis = ThesisVersion(
        company_id=company.id, version=1, status="published", rating="watch",
        thesis_markdown="# t", executive_summary="s",
    )
    db.add(thesis)
    db.flush()
    claim = Claim(company_id=company.id, thesis_version_id=thesis.id, statement="Sin url")
    db.add(claim)
    db.flush()
    db.add(ClaimEvidence(claim_id=claim.id, source_url=None, summary="x"))
    db.commit()
    memo = build_memo_markdown(db, company, thesis)
    assert "## Fuentes" not in memo


def test_draft_memo_is_a_whitelist_without_verdict_or_figures(db):
    company = _company(db)
    thesis = _full_thesis(db, company.id)
    thesis.status = "draft"
    thesis.hypothesis = "Valoración indicativa de 999 dólares por acción."
    thesis.executive_summary = "Margen de seguridad del 40 % según el modelo."
    db.commit()

    memo = build_memo_markdown(db, company, thesis, draft=True)

    assert memo.startswith("# Memo de tesis — AAPL (Apple)")
    assert "Versión 2 · estado borrador · generada" in memo
    assert "BORRADOR sin publicar" in memo
    # Nada de veredicto ni cifras de valoracion.
    for forbidden in (
        "rating", "rating compra", "999", "40 %", "Valoración y escenarios", "Bajista",
        "Margen de seguridad", "## Hipótesis", "## Resumen ejecutivo", "## Secciones",
        "Foso competitivo", "Ecosistema cerrado.", "## Fuentes", "sec.gov",
        "La base instalada monetiza servicios a doble digito.",
    ):
        assert forbidden not in memo, forbidden
    # Lo que si queda.
    assert "- Próximos resultados (2026-11-05)" in memo
    assert "## Criterios de invalidación" in memo
    assert "Confianza de datos 82/100" in memo
    assert memo.rstrip().endswith("ni recomendación de compra o venta.")


def test_published_memo_includes_full_analysis_without_approval_section_or_duplicates(db):
    company = _company(db)
    thesis = ThesisVersion(
        company_id=company.id, version=3, status="published", rating="seguimiento",
        thesis_markdown=(
            "# Tesis de AAPL — v3\n\n## 4. Últimos resultados\n| Métrica | Valor |\n| --- | --- |\n"
            "| Ingresos | 200 mil M |\n\n### Contexto documental recuperado\nFragmento citado."
        ),
        hypothesis="Mismo texto.", executive_summary="Mismo texto.",
    )
    db.add(thesis)
    db.flush()
    db.add(ThesisSection(thesis_version_id=thesis.id, company_id=company.id, section_key="approval", title="Aprobación Telegram", body="approved", order_index=900))
    db.commit()

    memo = build_memo_markdown(db, company, thesis)

    assert "## Análisis completo" in memo
    assert "### 4. Últimos resultados" in memo
    assert "| Ingresos | 200 mil M |" in memo
    assert "**Contexto documental recuperado**" in memo
    assert "# Tesis de AAPL" not in memo
    assert memo.count("Mismo texto.") == 1
    assert "## Hipótesis y resumen ejecutivo" in memo
    assert "Aprobación Telegram" not in memo
    assert "## Secciones" not in memo


def test_unpublishable_valuation_gets_visible_indicative_banner_and_rag_is_trimmed(db):
    company = _company(db)
    long_extract = (
        "Extracto documental (no verificado): Doc. Fuente: URL no disponible. Documento 1: " + "x" * 900
        + "\nExtracto documental (no verificado): Doc. Fuente: URL no disponible. Documento 2: " + "y" * 900
    )
    thesis = ThesisVersion(
        company_id=company.id, version=4, status="published", rating="seguimiento",
        thesis_markdown="# t\n\n## 23. Contexto\n" + long_extract,
        hypothesis="H.", executive_summary="S.",
    )
    db.add(thesis)
    db.flush()
    db.add(SourceAudit(
        thesis_version_id=thesis.id, passed=False,
        required_fixes=["Faltan entradas de valoración (variables del modelo): churn"],
    ))
    db.commit()

    memo = build_memo_markdown(db, company, thesis)

    assert "auditoría de fuentes de esta versión NO pasó" in memo
    assert "churn" in memo
    assert "texto del extracto omitido" in memo
    assert "Doc. Fuente: URL no disponible." in memo
    assert "x" * 50 not in memo
    assert memo.count("Doc. Fuente") == 1


def test_memo_renders_narrative_sections_and_cleans_internal_marks(db):
    company = _company(db)
    thesis = ThesisVersion(
        company_id=company.id, version=3, status="final", rating="watch",
        thesis_markdown=(
            "# t\n## Valoración\n- Estado: ok publicable=True\n"
            "| x | derivado | 0,2 | m | 10 hechos citados (3766320, 3765864) |\n- Margen (12345) legítimo\n"
            "| Margen FCF | 0,23 | fracción | 2025 | SEC |\n| Ratio | 0,23 | ratio | 2025 | SEC |\n"
            "| Ingresos | 200,97 mil M | USD | 2025 | SEC |"
        ),
        executive_summary="s",
        narrative_sections=[
            {"titulo": "Lo que cambió", "parrafos": ["Texto uno.", "Evidencia 1: Titular. Fuente: https://e.com/a"]},
            {"titulo": "Vieja - INFERIDO", "parrafos": ["INFERIDO: algo"]},
            {"titulo": "Vacía", "parrafos": []},
        ],
    )
    db.add(thesis)
    db.commit()
    memo = build_memo_markdown(db, company, thesis)
    assert "## Análisis narrativo" in memo
    assert "### Lo que cambió" in memo
    assert "Texto uno." in memo
    assert "- Evidencia 1: Titular." in memo
    assert "### Vacía" not in memo
    assert "### Vieja (interpretación, no confirmado)" in memo
    assert "Interpretación a partir de titulares, no confirmada: algo" in memo
    assert "publicable=" not in memo
    assert "3766320" not in memo
    assert "10 hechos citados" in memo
    assert "(12345)" in memo
    assert "| Margen FCF | 23 % | porcentaje |" in memo
    assert "| Ratio | 0,23 | ratio |" in memo
    assert "| Ingresos | 200,97 mil M | USD |" in memo
    assert "no publicada ni aprobada" in memo


def test_published_memo_has_no_unapproved_banner(db):
    company = _company(db)
    thesis = ThesisVersion(
        company_id=company.id, version=1, status="published", rating="watch",
        thesis_markdown="# t", executive_summary="s",
    )
    db.add(thesis)
    db.commit()
    memo = build_memo_markdown(db, company, thesis)
    assert "no publicada ni aprobada" not in memo
    assert "## Análisis narrativo" not in memo


def test_isolated_memo_is_labeled_not_persisted(db):
    company = _company(db)
    thesis = ThesisVersion(
        company_id=company.id, version=9, status="final", rating="watch",
        thesis_markdown="# t\n## Resumen\ncuerpo", executive_summary="s",
    )
    db.add(thesis)
    db.commit()
    memo = build_memo_markdown(db, company, thesis, isolated=True)
    assert "tesis de una ejecución aislada (no persistida)" in memo
    assert "ARTEFACTO DE PRUEBA AISLADA" in memo
    assert "no persistida" in memo
    assert "desde la versión persistida" not in memo
    assert "Texto de la tesis persistida" not in memo
    normal = build_memo_markdown(db, company, thesis)
    assert "desde la versión persistida" in normal
    assert "Texto de la tesis persistida" in normal


def test_fraction_row_to_percent_is_exact_and_conservative():
    from app.services.thesis_memo import _fraction_row_to_percent as f

    def row(v, u="fracción"):
        return f"| Margen | {v} | {u} | 2025 | SEC |"

    assert "| 23,45 % | porcentaje |" in f(row("0,2345"))
    assert "| 8,25 % | porcentaje |" in f(row("0,0825"))
    assert "| 23,456 % | porcentaje |" in f(row("0,23456"))
    assert "| 23 % | porcentaje |" in f(row("0,23"))
    assert "| 50 % | porcentaje |" in f(row("0,50"))
    assert "| -5 % | porcentaje |" in f(row("-0,05"))
    assert f(row("1")) == row("1")
    assert f(row("0,23", "ratio")) == row("0,23", "ratio")


def test_memo_money_uses_listing_currency_never_bare_dollar(db):
    """Una acción en EUR no puede exportarse con «$»: la cifra sería inventada.

    Regresión: el memo de SAN.MC (EUR) mostraba «Precio actual: $3.58» mientras
    la ficha formatea con CompanyOut.currency. El memo usa la divisa del
    listado, como la ficha (thesisMoney).
    """
    company = Company(
        ticker="SAN.MC", name="Banco Santander", exchange="BME", currency="EUR",
        sector="Finanzas", industry="Banca", company_type="bank",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    from app.models import FundamentalModelVersion

    db.add(FundamentalModelVersion(
        company_id=company.id, version=1, engine_version="test", algorithm_version="test",
        framework_key="dcf", horizon_years=10, status="ok", publishable=True,
        input_fingerprint="input", forecast_fingerprint="forecast",
        market_snapshot_fingerprint="market", valuation_snapshot_fingerprint="valuation",
    ))
    db.commit()
    thesis = ThesisVersion(
        company_id=company.id, version=1, status="published", rating="hold",
        thesis_markdown="# t", executive_summary="Resumen.", hypothesis="Hipótesis.",
        current_price=3.58, bear_value=2.9, base_value=3.6, bull_value=4.3,
        expected_value=3.62, margin_of_safety=0.011,
        scenario_probabilities={"bear": 0.2, "base": 0.6, "bull": 0.2},
        catalysts=[], invalidation_criteria=[],
    )
    db.add(thesis)
    db.commit()
    memo = build_memo_markdown(db, company, thesis)

    assert "| Bajista | 2,90 EUR | 20 % |" in memo
    assert "| Base | 3,60 EUR | 60 % |" in memo
    assert "Precio del modelo: 3,58 EUR · Valor esperado: 3,62 EUR · Margen de seguridad: 1,1 %" in memo
    assert "$" not in memo


def test_historical_margin_without_convention_is_warned_not_rewritten(db):
    company = _company(db)
    thesis = _full_thesis(db, company.id)
    thesis.current_price = 343.46
    thesis.expected_value = 120.53
    thesis.margin_of_safety = -0.649
    thesis.valuation_basis = {"model_version": "valuation-engines-v2"}
    thesis.executive_summary = "Margen original -64,9 %"
    db.flush()
    memo = build_memo_markdown(db, company, thesis)
    assert "sin convención de fórmula verificada" in memo
    assert "No comparar este porcentaje" in memo
    assert "Margen original -64,9 %" in memo
    assert "Margen de seguridad: -64,9 %" in memo
    assert float(thesis.margin_of_safety) == -0.649
    assert "-185" not in memo


@pytest.mark.parametrize("convention", [None, "future_unknown_convention"])
def test_absent_or_unrecognized_margin_convention_is_not_assumed(db, convention):
    company = _company(db)
    thesis = _full_thesis(db, company.id)
    thesis.valuation_basis = {"margin_of_safety_convention": convention}
    assert "sin convención de fórmula verificada" in build_memo_markdown(db, company, thesis)


def test_explicit_margin_convention_prints_formula(db):
    from app.valuation.margin_convention import MARGIN_OF_SAFETY_CONVENTION

    company = _company(db)
    thesis = _full_thesis(db, company.id)
    thesis.valuation_basis = {"margin_of_safety_convention": MARGIN_OF_SAFETY_CONVENTION}
    memo = build_memo_markdown(db, company, thesis)
    assert "Convención del margen de seguridad: (V - P) / V" in memo
    assert "sin convención de fórmula verificada" not in memo


def test_draft_does_not_disclose_margin_provenance_or_number(db):
    company = _company(db)
    thesis = _full_thesis(db, company.id)
    memo = build_memo_markdown(db, company, thesis, draft=True)
    assert "Convención del margen" not in memo
    assert "margen de seguridad histórico" not in memo
    assert "15,0 %" not in memo


def test_model_price_shows_quote_date_only_when_persisted(db):
    """Auditoría v1.0 (2026-10-27): «Precio actual» mentía — el precio
    persistido es el que usó el modelo al generar la versión. Se rotula
    «Precio del modelo» y la fecha de la cotización solo aparece si quedó
    persistida en valuation_basis; nunca una fecha inventada."""
    company = _company(db)
    thesis = _full_thesis(db, company.id)
    thesis.valuation_basis = {"price_as_of": "2026-10-20"}
    memo = build_memo_markdown(db, company, thesis)
    assert "Precio del modelo al 20 oct 2026: $200.00" in memo
    assert "Precio actual" not in memo

    thesis.valuation_basis = None
    memo = build_memo_markdown(db, company, thesis)
    assert "Precio del modelo: $200.00" in memo
    assert "Precio actual" not in memo


def test_narrative_paragraphs_render_as_separate_paragraphs(db):
    """Cada párrafo narrativo es un párrafo propio: con salto simple se
    fusionaban en uno solo en Markdown y salían pegados en el PDF."""
    company = _company(db)
    thesis = ThesisVersion(
        company_id=company.id, version=1, status="published", rating="watch",
        thesis_markdown="# t", executive_summary="s",
        narrative_sections=[{"titulo": "Foso", "parrafos": [
            "Primer párrafo del análisis.",
            "Segundo párrafo del análisis.",
            "Evidencia 10-K: dato uno.",
            "Evidencia 10-K: dato dos.",
        ]}],
    )
    db.add(thesis)
    db.commit()

    memo = build_memo_markdown(db, company, thesis)

    assert (
        "### Foso\nPrimer párrafo del análisis.\n\nSegundo párrafo del análisis.\n\n"
        "- Evidencia 10-K: dato uno.\n- Evidencia 10-K: dato dos."
    ) in memo
    # Las evidencias consecutivas siguen formando una sola lista.
    assert "dato uno.\n\n- Evidencia" not in memo


def test_memo_dates_use_web_short_spanish_format_not_iso(db):
    """Las fechas del memo van como la ficha («24 oct 2026»), nunca en ISO."""
    company = _company(db)
    thesis = _full_thesis(db, company.id)
    thesis.created_at = datetime(2026, 10, 20, 14, 3, tzinfo=UTC)
    thesis.updated_at = datetime(2026, 10, 24, 9, 41, tzinfo=UTC)
    thesis.valuation_basis = {"price_as_of": "2026-10-24"}
    db.commit()

    memo = build_memo_markdown(
        db, company, thesis, stale=True, latest_data_at=datetime(2026, 10, 27, tzinfo=UTC),
    )

    assert "generada 20 oct 2026, 14:03 UTC · actualizada 24 oct 2026, 09:41 UTC" in memo
    assert "hasta 27 oct 2026" in memo
    assert "Precio del modelo al 24 oct 2026: $200.00" in memo
    # El pie tambien en formato corto: «Generado 28 oct 2026, 22:29 UTC ...».
    assert re.search(r"Generado \d{1,2} [a-z]{3,4} \d{4}, \d{2}:\d{2} UTC", memo)
    # Ninguna marca del propio memo queda en ISO.
    assert "2026-10-20" not in memo
    assert "2026-10-24" not in memo
    assert "2026-10-27" not in memo
    # La fecha del catalizador se conserva tal cual está persistida: la ficha
    # la muestra igual y el memo no reescribe datos.
    assert "- Próximos resultados (2026-11-05)" in memo


def test_full_thesis_memo_in_english_keeps_stored_content(db):
    company = _company(db)
    thesis = _full_thesis(db, company.id)
    memo = build_memo_markdown(db, company, thesis, language="en")

    assert memo.startswith("# Thesis memo — AAPL (Apple)")
    assert "Version 2 · status published · rating buy" in memo
    assert "## Hypothesis" in memo and "## Executive summary" in memo
    # El contenido persistido no se traduce: sale como se genero.
    assert "La base instalada monetiza servicios a doble digito." in memo
    assert "| Scenario | Value | Probability |" in memo
    assert "| Bear | $150.00 | 20% |" in memo
    assert "| Bull | $300.00 | 25% |" in memo
    assert "Model price: $200.00 · Expected value: $235.00 · Margin of safety: 15.0%" in memo
    assert "## Catalysts" in memo and "- Próximos resultados (2026-11-05)" in memo
    assert "## Invalidation criteria" in memo
    assert "Data confidence 82/100 · source coverage 74/100 · red-team 61/100 · valuation risk 35/100" in memo
    assert "## Sections" in memo and "### Foso competitivo" in memo
    assert "## Sources" in memo
    assert "from stored version 2 (fingerprint fp-abc123)." in memo
    assert memo.rstrip().endswith(
        "Informational research document. It is NOT financial advice or a recommendation to buy or sell."
    )
    for spanish in ("Memo de tesis", "Versión", "Escenario", "Catalizadores", "Generado", "asesoramiento"):
        assert spanish not in memo


def test_sparse_thesis_memo_in_english_says_pending():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = _company(session)
        thesis = ThesisVersion(company_id=company.id, version=1, status="draft", thesis_markdown="# t", executive_summary="")
        session.add(thesis)
        session.commit()
        memo = build_memo_markdown(session, company, thesis, language="en", draft=True)
    assert "status draft" in memo
    assert "> Unpublished DRAFT." in memo
    assert "_Pending._" in memo and "_Pendiente._" not in memo


def test_archived_thesis_memo_in_english():
    """Tesis archivada (publicada con modelo no publicable): aviso y pie en inglés."""
    from app.models import FundamentalModelVersion

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = _company(session)
        for model in session.query(FundamentalModelVersion).all():
            model.publishable = False
        thesis = ThesisVersion(
            company_id=company.id, version=4, status="published", thesis_markdown="# t",
            executive_summary="resumen archivado", created_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
        session.add(thesis)
        session.commit()
        english = build_memo_markdown(session, company, thesis, language="en")
        spanish = build_memo_markdown(session, company, thesis)
    assert english == (
        "# Thesis memo - AAPL\n\n"
        "Archived thesis v4 (2026-09-01): The model is not publishable; the archived text and "
        "figures are not current analysis.\n\n"
        "The stored original is kept; this document does not publish its archived analysis.\n\n"
        "Informational research document. It is NOT financial advice or a recommendation to buy or sell.\n"
    )
    assert "resumen archivado" not in english
    # El castellano no cambia.
    assert spanish.startswith("# Memo de tesis - AAPL\n\nTesis archivada v4 (2026-09-01): El modelo no es")
    assert "El original persistido se conserva" in spanish


def test_english_memo_formats_amounts_and_dates_in_english(db):
    """Inglés: importes no USD con separadores ingleses (€ como símbolo) y fechas «Oct 20, 2026»."""
    company = _company(db)
    company.currency = "EUR"
    thesis = _full_thesis(db, company.id)
    thesis.created_at = datetime(2026, 10, 20, 14, 3, tzinfo=UTC)
    thesis.updated_at = datetime(2026, 10, 24, 9, 41, tzinfo=UTC)
    thesis.bull_value = 1234.5
    thesis.valuation_basis = {"price_as_of": "2026-10-24"}
    db.commit()

    english = build_memo_markdown(
        db, company, thesis, language="en", stale=True, latest_data_at=datetime(2026, 10, 27, tzinfo=UTC),
    )
    assert "generated Oct 20, 2026, 14:03 UTC · updated Oct 24, 2026, 09:41 UTC" in english
    assert "(up to Oct 27, 2026)" in english
    assert "| Bear | €150.00 | 20% |" in english
    assert "| Bull | €1,234.50 | 25% |" in english
    assert "Model price as of Oct 24, 2026: €200.00 · Expected value: €235.00" in english
    assert re.search(r"Generated [A-Z][a-z]{2} \d{1,2}, \d{4}, \d{2}:\d{2} UTC", english)
    for spanish in ("oct 2026", "EUR", "1.234,50"):
        assert spanish not in english

    # El castellano no cambia: código de divisa y formato es-ES.
    spanish = build_memo_markdown(db, company, thesis)
    assert "| Alcista | 1.234,50 EUR | 25 % |" in spanish
    assert "generada 20 oct 2026, 14:03 UTC" in spanish


def test_english_memo_other_currency_keeps_its_code():
    from app.services.thesis_memo import _money_en

    assert _money_en(1234.5, "GBP") == "1,234.50 GBP"
    assert _money_en(-12, "EUR") == "-€12.00"
    assert _money_en(343.46, "USD") == "$343.46"
    assert _money_en(None, "EUR") == "pending"
