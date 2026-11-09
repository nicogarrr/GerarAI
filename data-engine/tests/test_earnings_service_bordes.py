"""earnings_service: helpers de datos del workflow de resultados, con SQLite
real en memoria.

Cubierto aqui (solo helpers de datos, sin LLM ni orquestacion):
- _document_text: chunks ordenados por chunk_index unidos con "\\n", documento
  sin chunks -> "", lista vacia -> {}.
- _comparisons: latest por (metric, fiscal_year, fiscal_quarter) via setdefault
  con orden desc(fiscal_year), desc(created_at); metrica sin dato actual se
  omite; yoy ausente o yoy.value == 0 -> yoy_change None; trimestre None no
  coincide con la clave pedida.
- _promise_tracking: CallClaim con follow_up_required unido a Transcript de la
  company; overlap lexico (regex [a-z0-9]+) >= 3 -> "possible_update", si no
  "unresolved"; propagacion de later_verified; orden desc(created_at).
- _impact_direction: tone > 0.25 sin riesgos -> "positive"; tone < -0.25 o
  >= 3 riesgos -> "negative"; resto -> "mixed"; management_tone None -> {}.

NO cubierto a proposito (zona prohibida del encargo): las lineas 179-185
(ClaimIntelligenceService.scan_document), 245 (ValuationService.persist_output)
y 251-252/258-273 (ThesisService.generate con force_new_thesis) orquestan
claims/valoracion/tesis y quedan declaradas como no cubiertas. Tampoco se
prueba el LLM (_tone usa texto ya dado en otros tests) ni la capa de rutas.
"""

import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    CallClaim,
    Company,
    Document,
    DocumentChunk,
    EarningsRun,
    FinancialFact,
    Transcript,
)
from app.services.earnings_service import EarningsWorkflowService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = None
        yield session
    engine.dispose()


def _company(db: Session, ticker: str = "AAPL") -> Company:
    company = Company(
        ticker=ticker, name=f"{ticker} Inc.", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", cik="0000320193",
        company_type="holding", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _fact(
    db: Session, company: Company, metric: str, value: str,
    fiscal_year: int | None, fiscal_quarter: str | None,
    created_at: datetime | None = None,
) -> FinancialFact:
    fact = FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(value),
        period=f"{fiscal_year}-{fiscal_quarter}", fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
    )
    if created_at is not None:
        fact.created_at = created_at
    db.add(fact)
    db.commit()
    return fact


def test_document_text_concatena_chunks_ordenados(db: Session):
    company = _company(db)
    doc = Document(
        company_id=company.id, title="transcript", source_type="manual",
    )
    db.add(doc)
    db.commit()
    # Insertados desordenados a proposito: debe mandar chunk_index.
    for idx, texto in ((2, "dos"), (0, "cero"), (1, "uno")):
        db.add(DocumentChunk(document_id=doc.id, chunk_index=idx, text=texto))
    db.commit()

    resultado = EarningsWorkflowService()._document_text(db, [doc])

    assert resultado == {doc.id: "cero\nuno\ndos"}


def test_document_text_documento_sin_chunks_y_lista_vacia(db: Session):
    company = _company(db)
    doc = Document(
        company_id=company.id, title="vacio", source_type="manual",
    )
    db.add(doc)
    db.commit()
    servicio = EarningsWorkflowService()

    assert servicio._document_text(db, [doc]) == {doc.id: ""}
    assert servicio._document_text(db, []) == {}


def test_comparisons_con_yoy_calcula_cambio_exacto(db: Session):
    company = _company(db)
    actual = _fact(db, company, "revenue", "150", 2025, "Q1")
    previo = _fact(db, company, "revenue", "100", 2024, "Q1")

    resultado = EarningsWorkflowService()._comparisons(db, company, 2025, "Q1")

    # Valores esperados calculados con Decimal sobre lo realmente almacenado.
    cambio = (actual.value - previo.value) / abs(previo.value)
    assert set(resultado) == {"revenue"}
    assert resultado["revenue"] == {
        "current": str(actual.value),
        "prior_year": str(previo.value),
        "yoy_change": str(cambio),
        "current_fact_id": actual.id,
        "prior_year_fact_id": previo.id,
    }


def test_comparisons_sin_yoy_deja_campos_none(db: Session):
    company = _company(db)
    actual = _fact(db, company, "eps", "2.5", 2025, "Q2")

    resultado = EarningsWorkflowService()._comparisons(db, company, 2025, "Q2")

    assert resultado["eps"] == {
        "current": str(actual.value),
        "prior_year": None,
        "yoy_change": None,
        "current_fact_id": actual.id,
        "prior_year_fact_id": None,
    }


def test_comparisons_yoy_cero_no_divide(db: Session):
    company = _company(db)
    _fact(db, company, "fcf", "50", 2025, "Q3")
    previo = _fact(db, company, "fcf", "0", 2024, "Q3")

    resultado = EarningsWorkflowService()._comparisons(db, company, 2025, "Q3")

    assert resultado["fcf"]["prior_year"] == str(previo.value)
    assert resultado["fcf"]["yoy_change"] is None
    assert resultado["fcf"]["prior_year_fact_id"] == previo.id


def test_comparisons_metrica_sin_dato_actual_se_omite(db: Session):
    company = _company(db)
    _fact(db, company, "margen", "20", 2024, "Q1")

    resultado = EarningsWorkflowService()._comparisons(db, company, 2025, "Q1")

    assert resultado == {}


def test_comparisons_setdefault_conserva_el_mas_reciente(db: Session):
    company = _company(db)
    antiguo = _fact(
        db, company, "revenue", "140", 2025, "Q1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    reciente = _fact(
        db, company, "revenue", "150", 2025, "Q1",
        created_at=datetime(2026, 2, 1, tzinfo=UTC),
    )

    resultado = EarningsWorkflowService()._comparisons(db, company, 2025, "Q1")

    # La ordenacion pone primero el created_at mas nuevo y setdefault lo retiene.
    assert resultado["revenue"]["current_fact_id"] == reciente.id
    assert resultado["revenue"]["current_fact_id"] != antiguo.id
    assert resultado["revenue"]["current"] == str(reciente.value)


def test_comparisons_trimestre_none_no_coincide_con_la_clave(db: Session):
    company = _company(db)
    _fact(db, company, "revenue", "150", 2025, None)
    _fact(db, company, "revenue", "100", 2024, None)

    resultado = EarningsWorkflowService()._comparisons(db, company, 2025, "Q1")

    # La clave (metric, 2025, None) no es (metric, 2025, "Q1"): se omite.
    assert resultado == {}


def _claim(
    db: Session, company: Company, texto: str, *,
    follow_up: bool = True, later_verified: bool | None = None,
    created_at: datetime | None = None,
) -> CallClaim:
    transcript = Transcript(company_id=company.id, title="call", period="2025Q1")
    db.add(transcript)
    db.commit()
    claim = CallClaim(
        transcript_id=transcript.id, speaker="CEO", speaker_role="executive",
        claim=texto, claim_type="guidance", follow_up_required=follow_up,
        later_verified=later_verified,
    )
    if created_at is not None:
        claim.created_at = created_at
    db.add(claim)
    db.commit()
    return claim


def _overlap_esperado(claim: str, texto: str) -> int:
    return len(
        set(re.findall(r"[a-z0-9]+", claim.lower()))
        & set(re.findall(r"[a-z0-9]+", texto.lower()))
    )


def test_promise_tracking_possible_update_con_overlap_exacto(db: Session):
    company = _company(db)
    claim = _claim(
        db, company, "aumentaremos el dividendo un diez porciento",
        later_verified=True,
    )
    texto = "el dividendo sube un diez porciento este trimestre"

    resultado = EarningsWorkflowService()._promise_tracking(db, company, texto)

    esperado = _overlap_esperado(claim.claim, texto)
    assert esperado >= 3
    assert resultado == [
        {
            "call_claim_id": claim.id,
            "promise": claim.claim,
            "status": "possible_update",
            "lexical_overlap": esperado,
            "later_verified": True,
        }
    ]


def test_promise_tracking_unresolved_con_overlap_menor_a_3(db: Session):
    company = _company(db)
    claim = _claim(db, company, "abriremos una planta nueva en zaragoza")

    resultado = EarningsWorkflowService()._promise_tracking(
        db, company, "beneficio record del trimestre"
    )

    assert resultado == [
        {
            "call_claim_id": claim.id,
            "promise": claim.claim,
            "status": "unresolved",
            "lexical_overlap": 0,
            "later_verified": None,
        }
    ]


def test_promise_tracking_filtra_sin_follow_up_y_otra_company(db: Session):
    company = _company(db)
    otra = _company(db, ticker="MSFT")
    texto = "el dividendo sube un diez porciento este trimestre"
    _claim(
        db, company, "aumentaremos el dividendo un diez porciento",
        follow_up=False,
    )
    _claim(db, otra, "aumentaremos el dividendo un diez porciento")

    resultado = EarningsWorkflowService()._promise_tracking(db, company, texto)

    assert resultado == []


def test_promise_tracking_ordena_por_created_at_descendente(db: Session):
    company = _company(db)
    antiguo = _claim(
        db, company, "aumentaremos el dividendo un diez porciento",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    reciente = _claim(
        db, company, "lanzaremos el dividendo especial un diez porciento",
        created_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    texto = "el dividendo sube un diez porciento este trimestre"

    resultado = EarningsWorkflowService()._promise_tracking(db, company, texto)

    assert [r["call_claim_id"] for r in resultado] == [reciente.id, antiguo.id]


def test_impact_direction_positive_solo_con_tono_alto_y_sin_riesgos():
    servicio = EarningsWorkflowService()

    run = EarningsRun(management_tone={"score": 0.5}, risk_updates=[])
    assert servicio._impact_direction(run) == "positive"

    # Mismo tono alto pero con un riesgo: cae a mixed (no cumple >= 3).
    run = EarningsRun(
        management_tone={"score": 0.5}, risk_updates=[{"risk": "fx"}],
    )
    assert servicio._impact_direction(run) == "mixed"


def test_impact_direction_negative_por_tono_o_por_riesgos():
    servicio = EarningsWorkflowService()

    run = EarningsRun(management_tone={"score": -0.5}, risk_updates=[])
    assert servicio._impact_direction(run) == "negative"

    # Tono alto pero 3 riesgos: manda la regla de riesgos.
    run = EarningsRun(
        management_tone={"score": 0.5},
        risk_updates=[{"risk": "a"}, {"risk": "b"}, {"risk": "c"}],
    )
    assert servicio._impact_direction(run) == "negative"


def test_impact_direction_mixed_y_management_tone_none():
    servicio = EarningsWorkflowService()

    run = EarningsRun(management_tone={"score": 0.0}, risk_updates=[])
    assert servicio._impact_direction(run) == "mixed"

    # management_tone None: el `or {}` evita el AttributeError y da tono 0.
    run = EarningsRun(management_tone=None, risk_updates=[])
    assert servicio._impact_direction(run) == "mixed"
