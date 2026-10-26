"""Thesis memo (downloadable Markdown) contract tests.

The memo is the professional thesis deliverable: it must render every
persisted section verbatim, mark anything missing as "pendiente" (never
fabricate), and always close with the not-financial-advice disclaimer.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    Claim,
    ClaimEvidence,
    Company,
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
    assert "Precio actual: $200.00 · Valor esperado: $235.00 · Margen de seguridad: 15,0 %" in memo
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
    assert "hasta 2026-09-20" in memo


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
