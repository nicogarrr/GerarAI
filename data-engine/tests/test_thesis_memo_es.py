"""El memorando de la tesis se genera en español de UI, con tildes, sin
placeholders de plantilla y con los números internos redondeados.

Regresiones cubiertas:
- la plantilla salía en inglés ("# ASTS Thesis v25", "## 1. Executive Summary");
- la línea N/D llevaba el placeholder sin sustituir
  "(dado X, inferimos Y) con fuente https.";
- la base del tipo impositivo mostraba "clamped from -0.0060194747112082423"
  con 16 decimales y nota interna en inglés.
"""

import re
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import SessionLocal, init_db
from app.models import Company, FinancialFact, Position
from app.services.long_term_model_service import LongTermModelService
from app.services.thesis_service import ThesisService


def _company() -> Company:
    return Company(
        ticker="T",
        name="Test Co",
        exchange="E",
        currency="USD",
        sector="Software",
        industry="Application Software",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )


def test_render_markdown_en_espanol_sin_ingles_ni_claves_crudas():
    markdown = ThesisService()._render_markdown(
        _company(),
        {},
        {"passed": True, "source_coverage_score": 80, "unsupported_claims": 0},
        {},
        long_term_model={},
        version=3,
        hypothesis="Hipótesis de prueba.",
        catalysts=[],
        invalidation_criteria=["Un criterio."],
        scenario_probabilities=None,
    )
    assert markdown.startswith("# Tesis de T — v3")
    for header in (
        "## 1. Resumen ejecutivo",
        "## 2. Hipótesis",
        "## 13. Valoración",
        "## 14. DCF inverso",
        "## 19. Auditoría de fuentes",
        "## 20. Fuentes",
        "## 21. Datos pendientes",
        "## 22. Procedencia de los inputs",
    ):
        assert header in markdown
    for english in (
        "Executive Summary",
        "Thesis v",
        "Required revenue growth",
        "Reverse DCF unavailable",
        "Source Audit",
        "Probabilities",
        "Datos Pendientes",
    ):
        assert english not in markdown
    assert "Trazabilidad de los claims y cálculos de ESTA corrida" in markdown
    assert "no verifica la veracidad de las fuentes): superada" in markdown
    assert "Elegibilidad técnica para publicación" in markdown
    assert "Versión del modelo fundamental usada en esta corrida" in markdown
    assert "independiente del número de versión de esta tesis" in markdown
    assert "NO acredita persistencia duradera" in markdown
    assert "Semilla maestra de la empresa" in markdown
    assert "Probabilidades: pendiente" in markdown


def test_pendings_nd_sin_placeholder_de_plantilla():
    model = {
        "assumptions": {
            "terminal_growth": {
                "value": 0.03,
                "unit": "decimal",
                "source_type": "model_policy",
                "basis": "política de crecimiento terminal del marco de la empresa",
                "source_fact_ids": [],
                "confidence": 0.4,
            },
        },
    }
    text = ThesisService()._pendings_markdown({}, model, {})
    assert "`terminal_growth`: N/D (supuesto sin base documentada)." in text
    assert "(dado X, inferimos Y)" not in text
    assert "con fuente https." not in text


def _fact(db, company, metric: str, value: float, year: int) -> None:
    db.add(
        FinancialFact(
            company_id=company.id,
            metric=metric,
            value=Decimal(str(value)),
            unit="USD",
            period=f"FY{year}",
            fiscal_year=year,
            fiscal_quarter="FY",
            source_type="test_thesis_memo_es",
            is_reported=True,
            confidence=Decimal("0.95"),
        )
    )


def test_tax_clamp_basis_redondeada_y_en_espanol():
    init_db()
    db = SessionLocal()
    try:
        company = Company(
            ticker="TAXES",
            name="Tax Clamp Test Co",
            exchange="TEST",
            currency="USD",
            sector="Software",
            industry="Application Software",
            company_type="standard",
            valuation_model="standard_dcf",
            special_sources=[],
            special_risks=[],
            factor_tags=["quality"],
        )
        db.add(company)
        db.flush()
        db.add(Position(company_id=company.id, market_price=Decimal("50")))
        for year in (2023, 2024, 2025):
            _fact(db, company, "revenue", 100.0, year)
            _fact(db, company, "income_before_tax", 100.0, year)
            # Tipo efectivo negativo: el clamp a [0, 60 %] debe declararse
            # redondeado y en español, nunca con el float crudo.
            _fact(db, company, "income_tax_expense", -0.6019474711208242, year)
        db.commit()

        result = LongTermModelService().build(db, company, horizon=5, commit=False)
        basis = result["assumptions"]["effective_tax_rate"]["basis"]
        assert "acotado al rango [0 %, 60 %]" in basis
        assert "clamped from" not in basis
        assert "-0,60 %" in basis
        assert "-0.60%" not in basis
        assert not re.search(r"\d\.\d{6,}", basis), basis
    finally:
        company = db.scalar(select(Company).where(Company.ticker == "TAXES"))
        if company:
            db.execute(delete(FinancialFact).where(FinancialFact.company_id == company.id))
            db.execute(delete(Position).where(Position.company_id == company.id))
            db.delete(company)
            db.commit()
        db.close()


def test_cifras_y_claves_del_memo_en_es():
    from app.services.memo_text_es import number_es, term_es

    assert number_es("416161000000.000000", "USD") == "416.161.000.000 USD"
    assert number_es("-0.0060194747112082423") == "-0,00602"
    assert number_es("12.5") == "12,5"
    assert term_es("capex_to_revenue") == "Capex sobre ingresos"
    assert term_es("algo_nuevo") == "algo nuevo"
    facts = ThesisService()._facts_markdown(
        {"revenue": type("F", (), {"value": Decimal("416161000000.000000"), "unit": "USD", "period": "FY2025", "source_type": "sec_filing", "source_id": 23})()}
    )
    assert "| Ingresos | 416,16 mil M | USD | FY2025 | Informe SEC #23 |" in facts
    assert "revenue" not in facts


def test_drivers_ausentes_y_noticias_de_bufetes_no_llegan_al_memo():
    from app.services.memo_text_es import term_es
    from app.services.ticker_news_lane import is_law_firm_solicitation

    assert term_es("addressable_subscribers") == "suscriptores direccionables"
    assert term_es("price_per_gb") == "precio por GB"
    assert is_law_firm_solicitation(
        "ASTS Investors Have Opportunity to Lead AST SpaceMobile, Inc. Securities Fraud Lawsuit with SBS Law"
    )
    assert is_law_firm_solicitation(
        "ASTS Investors Have Opportunity to Lead AST SpaceMobile, Inc. Securities Fraud Lawsuit"
    )
    assert not is_law_firm_solicitation("AST SpaceMobile launches BlueBird 6 satellite")
    assert not is_law_firm_solicitation("AST SpaceMobile faces securities lawsuit, Reuters reports")


def test_marcos_sector_y_unidades_en_espanol_sin_perder_datos():
    from app.services.company_framework import FRAMEWORKS
    from app.services.memo_text_es import primary_question_es, sector_es, term_es, unit_es

    for framework in FRAMEWORKS.values():
        question = primary_question_es(framework.primary_question)
        assert question.startswith("¿"), framework.primary_question
    assert sector_es("Information Technology") == "Tecnología de la información"
    assert sector_es("Sector Raro") == "Sector Raro"  # desconocido: tal cual, no se inventa
    assert unit_es("shares") == "acciones" and unit_es("USD") == "USD"
    assert term_es("capital_expenditure") == "Gasto de capital (capex)"
    assert term_es("cash_and_equivalents") == "Caja y equivalentes"


def test_elegibilidad_tecnica_distinguida_de_trazabilidad():
    audit = {"passed": True, "source_coverage_score": 80, "unsupported_claims": 0}
    base = dict(
        long_term_model={}, version=3, hypothesis="H.", catalysts=[],
        invalidation_criteria=["Un criterio."], scenario_probabilities=None,
    )
    md_pub = ThesisService()._render_markdown(
        _company(), {"publishable": True}, audit, {}, **base)
    md_nopub = ThesisService()._render_markdown(
        _company(), {"publishable": False}, audit, {}, **base)
    assert "NO es la aprobación humana ni la publicación): sí" in md_pub
    assert "NO es la aprobación humana ni la publicación): no" in md_nopub
    # La trazabilidad de la corrida es la misma en ambos: no van juntas.
    assert "ESTA corrida" in md_pub and "ESTA corrida" in md_nopub


def _render(valuation, audit, ltm):
    return ThesisService()._render_markdown(
        _company(), valuation, audit, {},
        long_term_model=ltm, version=3, hypothesis="H.", catalysts=[],
        invalidation_criteria=["Un criterio."], scenario_probabilities=None,
    )


def test_matriz_estados_copy_no_inventa_estado_tesis():
    # Matriz de fixtures: audit passed x publishable x persistence/status del
    # motor. El markdown NUNCA debe afirmar un estado de la tesis (borrador,
    # publicada, aprobada) ni durabilidad del modelo: eso vive en registros.
    audit_ok = {"passed": True, "source_coverage_score": 95, "unsupported_claims": 0}
    audit_fail = {"passed": False, "source_coverage_score": 60, "unsupported_claims": ["claim x"]}
    ltm_aislado = {"persistence": {"version": 7, "status": "persisted"},
                   "status": "complete"}
    for valuation in ({"publishable": True}, {"publishable": False}, {}):
        for audit in (audit_ok, audit_fail):
            for ltm in ({}, ltm_aislado):
                md = _render(valuation, audit, ltm)
                assert "borrador" not in md
                assert "tesis publicada" not in md and "tesis aprobada" not in md
                assert "Versión persistida del modelo" not in md
    md = _render({"publishable": True}, audit_ok, ltm_aislado)
    assert "Elegibilidad técnica para publicación" in md
    assert "NO es la aprobación humana ni la publicación): sí" in md
    assert "Versión del modelo fundamental usada en esta corrida: `7`" in md
    assert "NO acredita persistencia duradera" in md
    # El estado del motor sale en español legible, nunca como código entre comillas.
    assert "Estado del análisis del modelo fundamental (no es el estado de esta tesis): complete." in md
    md_fail = _render({"publishable": True}, audit_fail, {})
    assert "ESTA corrida" in md_fail and "no superada" in md_fail
    assert "NO es la aprobación humana ni la publicación): no" in md_fail
