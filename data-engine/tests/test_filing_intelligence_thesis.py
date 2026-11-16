"""Filing -> criterio de tesis: ``analyze_document`` evalúa las reglas ``metrica:X``
con el FinancialFact que aporta el propio filing y alerta en high solo si cruza."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import (
    Base,
    Company,
    Document,
    DocumentChunk,
    FinancialFact,
    ResearchAlert,
    Tenant,
    ThesisVersion,
    WatchItem,
)
from app.services.filing_intelligence import KEY, analyze_document

TEXT = "Item 1A. Risk Factors\nOur supplier concentration may delay commercial production."


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        tenant = Tenant(external_id="thesis-filing", name="One")
        company = Company(
            ticker="THFI",
            name="ThesisFiling",
            exchange="NASDAQ",
            currency="USD",
            company_type="holding",
            valuation_model="unassigned",
        )
        session.add_all([tenant, company])
        session.flush()
        session.info.update(tenant_id=tenant.id, company_id=company.id)
        session.add(WatchItem(symbol="THFI"))
        session.commit()
        yield session
    engine.dispose()


def document(db, *, form="10-Q", text=TEXT, number=1, tenant=None):
    doc = Document(
        tenant_id=tenant or db.info["tenant_id"],
        company_id=db.info["company_id"],
        title=form,
        source_type="SEC",
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{number}/report.htm",
        checksum=f"hash-{number}",
        published_at=datetime(2026, 10, 1, tzinfo=UTC),
        metadata_={"form": form, "report_date": "2026-09-30"},
    )
    db.add(doc)
    db.flush()
    if text:
        db.add(DocumentChunk(tenant_id=doc.tenant_id, document_id=doc.id, chunk_index=0, text=text))
    db.commit()
    return doc


def thesis(db, rules):
    t = ThesisVersion(
        tenant_id=db.info["tenant_id"],
        company_id=db.info["company_id"],
        version=1,
        thesis_markdown="x",
        executive_summary="y",
        invalidation_rules=rules,
    )
    db.add(t)
    db.commit()
    return t


def fact(db, metric, value, *, year, doc_id=None, quarter=None, period=None):
    f = FinancialFact(
        tenant_id=db.info["tenant_id"],
        company_id=db.info["company_id"],
        metric=metric,
        value=Decimal(str(value)) if value is not None else None,
        unit="ratio",
        period=period or f"FY{year}",
        fiscal_year=year,
        fiscal_quarter=quarter,
        source_id=doc_id,
        source_type="sec",
        filed=date(2026, 10, 1),
    )
    db.add(f)
    db.commit()
    return f


def test_criterion_crossed_by_filing_alert_high(db):
    thesis(
        db,
        [{"metric": "metrica:roic", "operator": "<", "threshold": 0.08, "description": "roic bajo mínimo"}],
    )
    fact(db, "roic", 0.10, year=2025)  # último evaluado
    doc = document(db, number=2)
    new = fact(db, "roic", 0.06, year=2026, doc_id=doc.id)  # lo aporta ESTE filing
    result = analyze_document(db, doc)
    db.commit()
    check = result["thesis_check"][0]
    assert check["status"] == "crossed"
    assert check["metric"] == "roic" and check["fact_id"] == new.id
    assert check["operator"] == "<" and check["threshold"] == 0.08
    assert check["observed"] == pytest.approx(0.06)
    alert = db.scalar(select(ResearchAlert))
    assert alert.severity == "high"
    assert alert.alert_type == "thesis_invalidation_filing"
    assert "roic" in alert.message and "0.08" in alert.message
    assert doc.source_url in alert.message and doc.checksum in alert.message
    assert alert.metadata_["matching"] == ["watchlist"]
    assert alert.channels == ["in_app"]
    # Reejecutar el mismo checksum no duplica (fingerprint con regla + hecho).
    analyze_document(db, doc)
    db.commit()
    assert len(db.scalars(select(ResearchAlert)).all()) == 1


def test_criterion_not_crossed_keeps_normal_alert(db):
    thesis(db, [{"metric": "metrica:roic", "operator": "<", "threshold": 0.08}])
    fact(db, "roic", 0.09, year=2025)
    doc = document(db, number=2)
    fact(db, "roic", 0.10, year=2026, doc_id=doc.id)
    result = analyze_document(db, doc)
    db.commit()
    assert result["thesis_check"][0]["status"] == "not_crossed"
    alert = db.scalar(select(ResearchAlert))
    assert alert.severity == "medium"
    assert alert.alert_type != "thesis_invalidation_filing"


def test_missing_never_fires(db):
    # Sin regla metrica: o sin FinancialFact nuevo del filing: missing, no dispara.
    thesis(
        db,
        [
            {"metric": "metrica:goodwill", "operator": ">", "threshold": 1000},
            {"metric": "precio", "operator": "<", "threshold": 5},
        ],
    )
    doc = document(db)
    result = analyze_document(db, doc)
    db.commit()
    statuses = {c["metric"]: c["status"] for c in result["thesis_check"]}
    assert statuses == {"goodwill": "missing"}  # la regla de precio no se evalúa aquí
    alert = db.scalar(select(ResearchAlert))
    assert alert is None or alert.severity == "medium"


def test_reingested_same_year_fact_is_not_new(db):
    thesis(db, [{"metric": "metrica:roic", "operator": "<", "threshold": 0.08}])
    old_doc = document(db, number=1)
    fact(db, "roic", 0.10, year=2026, doc_id=old_doc.id)
    doc = document(db, number=2)
    fact(db, "roic", 0.06, year=2026, doc_id=doc.id)  # mismo ejercicio: no es dato nuevo
    result = analyze_document(db, doc)
    db.commit()
    assert result["thesis_check"][0]["status"] == "missing"
    assert not any(a.severity == "high" for a in db.scalars(select(ResearchAlert)).all())


def test_quarterly_flow_metric_is_ignored_like_observe(db):
    # Flujo trimestral con umbral anual: misma exclusión que observe().
    thesis(db, [{"metric": "metrica:revenue", "operator": "<", "threshold": 1000}])
    doc = document(db)
    fact(db, "revenue", 100, year=2026, quarter="Q3", doc_id=doc.id)
    result = analyze_document(db, doc)
    db.commit()
    assert result["thesis_check"][0]["status"] == "missing"
    assert not any(a.severity == "high" for a in db.scalars(select(ResearchAlert)).all())


def test_unresolvable_symbol_does_not_block(db):
    db.add(WatchItem(symbol="NOSUCH.XK"))
    db.commit()
    doc = document(db)
    result = analyze_document(db, doc)
    db.commit()
    assert result["status"] in {"insufficient_data", "changed", "ready"}
    assert db.scalar(select(ResearchAlert)).metadata_["matching"] == ["watchlist"]


def test_insufficient_data_keeps_new_filing_reason_in_metadata(db):
    doc = document(db, text=None, number=3)
    result = analyze_document(db, doc)
    db.commit()
    assert result["status"] == "insufficient_data"
    assert result["reason"]
    assert doc.metadata_[KEY]["reason"] == result["reason"]
    alert = db.scalar(select(ResearchAlert))
    assert alert.alert_type == "new_filing"
    assert alert.title.startswith("Documento oficial nuevo")


def test_no_thesis_no_check(db):
    doc = document(db)
    result = analyze_document(db, doc)
    assert result["thesis_check"] == []
    assert result["thesis_version_id"] is None


def test_sin_chunks_el_hecho_estructurado_evalua_la_tesis(db):
    # Regresión auditor: un filing sin chunks pero con FinancialFact propio que
    # cruza la tesis debe alertar en high igual que uno con texto; reason se
    # conserva en metadata.
    thesis(
        db,
        [{"metric": "metrica:roic", "operator": "<", "threshold": 0.08, "description": "roic bajo mínimo"}],
    )
    doc = document(db, text=None, number=3)
    fact(db, "roic", 0.06, year=2026, doc_id=doc.id)
    result = analyze_document(db, doc)
    db.commit()
    assert result["status"] == "insufficient_data"
    assert "texto" in result["reason"]
    assert result["thesis_check"][0]["status"] == "crossed"
    alert = db.scalar(select(ResearchAlert))
    assert alert.severity == "high"
    assert alert.alert_type == "thesis_invalidation_filing"
    assert alert.metadata_["reason"] == result["reason"]


def test_sin_chunks_sin_cruce_alerta_media_como_antes(db):
    thesis(
        db,
        [{"metric": "metrica:roic", "operator": "<", "threshold": 0.08, "description": "roic bajo mínimo"}],
    )
    doc = document(db, text=None, number=4)
    fact(db, "roic", 0.12, year=2026, doc_id=doc.id)  # no cruza
    result = analyze_document(db, doc)
    db.commit()
    assert result["thesis_check"][0]["status"] != "crossed"
    alert = db.scalar(select(ResearchAlert))
    assert alert.severity == "medium"
    assert alert.alert_type == "new_filing"
    assert alert.metadata_["reason"] == result["reason"]


def test_ratio_nuevo_trimestre_del_mismo_ejercicio_es_dato_nuevo(db):
    # Regresión auditor (2): ROIC Q3 2026 frente a Q1 2026 (mismo ejercicio) es
    # periodo nuevo: evalúa y cruza. Antes salía missing por comparar solo año.
    thesis(db, [{"metric": "metrica:roic", "operator": "<", "threshold": 0.08}])
    fact(db, "roic", 0.10, year=2026, quarter="Q1", period="2026:Q1")
    doc = document(db, number=2)
    fact(db, "roic", 0.06, year=2026, quarter="Q3", period="2026:Q3", doc_id=doc.id)
    result = analyze_document(db, doc)
    db.commit()
    check = result["thesis_check"][0]
    assert check["status"] == "crossed"
    assert check["period"] == "2026:Q3"
    alert = db.scalar(select(ResearchAlert))
    assert alert.severity == "high"


def test_mismo_trimestre_reingestado_no_es_nuevo(db):
    thesis(db, [{"metric": "metrica:roic", "operator": "<", "threshold": 0.08}])
    old = document(db, number=1)
    fact(db, "roic", 0.10, year=2026, quarter="Q3", period="2026:Q3", doc_id=old.id)
    doc = document(db, number=2)
    fact(db, "roic", 0.06, year=2026, quarter="Q3", period="2026:Q3", doc_id=doc.id)
    result = analyze_document(db, doc)
    db.commit()
    assert result["thesis_check"][0]["status"] == "missing"
    assert not any(a.severity == "high" for a in db.scalars(select(ResearchAlert)).all())


def test_hechos_previos_con_source_id_null_cuentan(db):
    # Regresión auditor (3): un hecho previo sin source_id (NULL) no debe
    # desaparecer del "anterior" (el != de SQL excluye NULL).
    thesis(db, [{"metric": "metrica:roic", "operator": "<", "threshold": 0.08}])
    fact(db, "roic", 0.10, year=2026)  # doc_id=None -> source_id NULL
    doc = document(db, number=2)
    fact(db, "roic", 0.06, year=2025, doc_id=doc.id)  # ejercicio ANTERIOR: no es nuevo
    result = analyze_document(db, doc)
    db.commit()
    assert result["thesis_check"][0]["status"] == "missing"
    assert not any(a.severity == "high" for a in db.scalars(select(ResearchAlert)).all())


def test_criterios_corruptos_guardados_no_rompen(db):
    # Rama: normalize_rules ValueError -> sin check, análisis normal.
    t = ThesisVersion(
        tenant_id=db.info["tenant_id"],
        company_id=db.info["company_id"],
        version=1,
        thesis_markdown="x",
        executive_summary="y",
        invalidation_rules=[{"metric": "metrica:roic", "operator": "~", "threshold": 0.08}],
    )
    db.add(t)
    db.commit()
    doc = document(db)
    fact(db, "roic", 0.06, year=2026, doc_id=doc.id)
    result = analyze_document(db, doc)
    db.commit()
    assert result["thesis_check"] == []


def test_fact_value_none_devuelve_none(db):
    # Rama defensiva: value NULL (el modelo lo prohíbe en BD) -> None.
    from app.services.filing_intelligence import _fact_value

    f = FinancialFact(
        tenant_id=db.info["tenant_id"],
        company_id=db.info["company_id"],
        metric="roic",
        value=None,
        unit="ratio",
        period="FY2026",
        fiscal_year=2026,
        source_type="sec",
        filed=date(2026, 10, 1),
    )
    assert _fact_value(db, db.info["company_id"], "roic", f) is None


def test_metrica_por_accion_reexpresada_por_split(db):
    # Rama: métrica por acción pasa por split_factor_for_fact (sin split: 1).
    thesis(db, [{"metric": "metrica:eps_diluted", "operator": ">", "threshold": 1.0}])
    doc = document(db)
    fact(db, "eps_diluted", 2.0, year=2026, doc_id=doc.id)
    result = analyze_document(db, doc)
    db.commit()
    assert result["thesis_check"][0]["status"] == "crossed"


def test_documento_sin_fecha_de_publicacion(db):
    # Rama: _citation con published_at None.
    doc = document(db, number=9)
    doc.published_at = None
    db.commit()
    result = analyze_document(db, doc)
    db.commit()
    assert result["source"]["published_at"] is None
