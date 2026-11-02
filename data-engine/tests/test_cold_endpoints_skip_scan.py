"""Camino en frio de data-health y metric-coverage: barrido perezoso (0122).

El piloto mido en prod el coste en frio tras la cache de 003c1644:
/api/data-health y /api/screeners/metric-coverage seguian en 17-18 s
(la mejora solo era cache caliente). Causa medida en el laboratorio: el
group-by con count(distinct) leia toda la porcion de cada capa y el contexto
del datalist hacia una consulta de outputs por empresa (N+1).

Estos tests fijan:
1. EQUIVALENCIA exacta de resultados frente a la semantica anterior (mismos
   grupos, mismos conteos, mismo max por fuente; mismas metricas de
   contexto, incluida la regla rara de tesis_publicada).
2. PLAN MEDIDO: sqlite conserva GROUP BY; PG usa sondas en dos niveles con
   rango INTEGER explicito, no la CTE antigua descartada (>96 s, PR3929). metric-coverage conserva
   el barrido perezoso medido mas rapido y no escala con empresas (guardia de
   nº de sentencias; el codigo anterior hacia 1 consulta por empresa con
   valoracion y la supera de lejos).
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.entities import (
    Base,
    Company,
    FinancialFact,
    MarketPrice,
    NewsEvent,
    Tenant,
    ThesisVersion,
    ValuationModel,
    ValuationOutput,
)
from app.services import screener_context_metrics as scm
from app.services.data_health_service import inventory
from app.services.screener_service import ScreenerService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as session:
        session.add_all([Tenant(id=1, external_id="one"), Tenant(id=2, external_id="two")])
        for i in (1, 2, 3):
            session.add(Company(id=i, ticker=f"C{i}", name=f"Co{i}", exchange="X",
                                currency="EUR", company_type="mature", valuation_model="dcf"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def _contador(engine):
    sentencias = []
    event.listen(engine, "before_cursor_execute",
                 lambda conn, cursor, statement, parameters, context, executemany:
                 sentencias.append(statement))
    return sentencias


def _fact(company_id, tenant_id, source, updated, **kw):
    return FinancialFact(company_id=company_id, tenant_id=tenant_id, metric=kw.pop("metric", "sales"),
                         value=Decimal("1"), period="FY", source_type=source,
                         is_reported=True, updated_at=updated, **kw)


def test_inventory_equivalencia_exacta_multifuente(db):
    """Mismos grupos/conteos/max que la semantica del group-by, por capa."""
    now = datetime.now(UTC)
    viejo = now - timedelta(days=3)
    nuevo = now - timedelta(days=1)
    db.add_all([
        _fact(1, 1, "SEC", viejo), _fact(2, 1, "SEC", nuevo), _fact(2, 1, "SEC", viejo),
        _fact(1, 1, "ESEF", nuevo),
        _fact(3, 2, "SEC", now),  # otro tenant: no cuenta
        _fact(1, 1, "seed", now),  # fuente excluida
        MarketPrice(company_id=1, date=nuevo.date(), close=10, source="yfinance", updated_at=nuevo),
        MarketPrice(company_id=1, date=viejo.date(), close=10, source="yfinance", updated_at=viejo),
        MarketPrice(company_id=2, date=nuevo.date(), close=10, source="stooq", updated_at=nuevo),
        MarketPrice(company_id=3, date=nuevo.date(), close=0, source="stooq", updated_at=now),  # close 0: fuera
        NewsEvent(company_id=1, tenant_id=1, date=now, title="t", source="gdelt", url="u",
                  updated_at=nuevo),
    ])
    db.info.pop("tenant_id")  # sembrar tenant 2 sin el guard de escritura
    db.commit()
    db.info["tenant_id"] = 1
    result = inventory(db, now=now)
    por_capa = {}
    for row in result["sources"]:
        if row["source"] is not None:
            por_capa[(row["layer"], row["source"])] = row

    facts_sec = por_capa[("Fundamentales", "SEC")]
    assert facts_sec["covered"] == 2  # empresas 1 y 2, no la 3 (otro tenant)
    assert facts_sec["last_update"] == nuevo.isoformat()  # max, no la primera
    facts_esef = por_capa[("Fundamentales", "ESEF")]
    assert facts_esef["covered"] == 1

    prices = por_capa[("Precios diarios", "yfinance")]
    assert prices["covered"] == 1
    assert prices["last_update"] == nuevo.isoformat()
    stooq = por_capa[("Precios diarios", "stooq")]
    assert stooq["covered"] == 1  # la empresa 3 tiene close=0: no cuenta

    news = por_capa[("Noticias", "gdelt")]
    assert news["covered"] == 1
    assert news["last_update"] == nuevo.isoformat()

    # Capa vacia conserva su fila "empty".
    docs = [r for r in result["sources"] if r["layer"] == "Documentos"]
    assert docs[0]["status"] == "empty"


def test_inventory_conserva_agregacion_medida_sin_cte_recursiva(db):
    """PR3929: la CTE fue peor en prod. Una agregacion por capa, no N+1."""
    engine = db.get_bind()
    db.add(_fact(1, 1, "SEC", datetime.now(UTC)))
    db.commit()
    sentencias = _contador(engine)
    result = inventory(db)
    assert not any("WITH RECURSIVE" in statement for statement in sentencias)
    aggregate_queries = [
        statement for statement in sentencias
        if "count(DISTINCT" in statement and "GROUP BY" in statement
    ]
    assert len(aggregate_queries) == 4, aggregate_queries
    assert all("max(" in statement for statement in aggregate_queries)
    for table in ("financial_facts", "documents", "news_events"):
        query = next(statement for statement in aggregate_queries if f"FROM {table}" in statement)
        assert f"{table}.tenant_id =" in query
    facts = next(row for row in result["sources"]
                 if row["layer"] == "Fundamentales" and row["source"] == "SEC")
    assert facts["covered"] == 1


def _montar_empresas_valoradas(db, n):
    modelos = []
    for i in range(n):
        company = Company(ticker=f"V{i}", name=f"VCo{i}", exchange="X", currency="EUR",
                          company_type="mature", valuation_model="dcf")
        db.add(company)
        db.flush()
        model = ValuationModel(company_id=company.id, model_type="dcf", version=1, status="ok")
        db.add(model)
        db.flush()
        db.add(ValuationOutput(valuation_model_id=model.id, scenario="base",
                               output_payload={"margin_of_safety": "0.25", "trace": {
                                   "margin_of_safety_convention": "discount_to_value_v1"}}))
        modelos.append(model)
    db.commit()
    return modelos


def test_metric_coverage_sin_n_mas_uno(db):
    """Rojo sin el cambio: antes 1 consulta de outputs por empresa (N+1)."""
    engine = db.get_bind()
    _montar_empresas_valoradas(db, 60)
    db.add(_fact(1, 1, "SEC", datetime.now(UTC)))
    db.commit()
    sentencias = _contador(engine)
    ScreenerService()._metric_coverage_uncached(db)
    assert len(sentencias) <= 12, f"{len(sentencias)} sentencias: escala con el universo"


def _nombres_contexto_esperados(db, companies):
    """Semantica ANTERIOR calculada con el codigo compartido (context_observations)."""
    observed = scm.context_observations(db, scm.CONTEXT_METRICS, companies)
    names = set()
    for per_company in observed.values():
        names.update(per_company)
    if not any(
        obs.get(scm.HAS_THESIS) is not None and obs[scm.HAS_THESIS].value == 1
        for obs in observed.values()
    ):
        names -= {scm.HAS_THESIS, scm.PUBLISHED_THESIS}
    return sorted(names)


def test_contexto_equivalente_a_la_semantica_anterior(db):
    companies = db.scalars(sa.select(Company)).all()
    # Sin tesis ni valoraciones: ningun nombre.
    assert scm.context_metrics_with_data(db) == _nombres_contexto_esperados(db, companies) == []
    # Tesis solo en borrador: tiene_tesis y tesis_publicada aparecen (regla
    # rara heredada: publicada se mantiene aunque nadie la tenga publicada).
    db.add(ThesisVersion(company_id=1, tenant_id=1, version=1, status="draft",
                         thesis_markdown="x", executive_summary="x"))
    db.commit()
    assert scm.context_metrics_with_data(db) == _nombres_contexto_esperados(db, companies)
    assert scm.context_metrics_with_data(db) == sorted([scm.HAS_THESIS, scm.PUBLISHED_THESIS])
    # Valoracion con margen conocido: margen_seguridad.
    _montar_empresas_valoradas(db, 3)
    assert scm.context_metrics_with_data(db) == _nombres_contexto_esperados(db, companies)
    assert scm.MARGIN_OF_SAFETY in scm.context_metrics_with_data(db)


def test_contexto_margen_solo_si_la_ultima_version_lo_tiene(db):
    # v2 insufficient_data tapa la v1 con margen: la empresa NO tiene el dato.
    company = db.get(Company, 1)
    v1 = ValuationModel(company_id=company.id, model_type="dcf", version=1, status="ok")
    db.add(v1)
    db.flush()
    db.add(ValuationOutput(valuation_model_id=v1.id, scenario="base",
                           output_payload={"margin_of_safety": "0.25", "trace": {
                               "margin_of_safety_convention": "discount_to_value_v1"}}))
    v2 = ValuationModel(company_id=company.id, model_type="dcf", version=2,
                        status="insufficient_data")
    db.add(v2)
    db.commit()
    assert scm.MARGIN_OF_SAFETY not in scm.context_metrics_with_data(db)
    # Convencion desconocida: tampoco cuenta.
    db.delete(v2)
    v1.outputs if hasattr(v1, "outputs") else None
    for out in db.scalars(sa.select(ValuationOutput)).all():
        out.output_payload = {"margin_of_safety": "0.25", "trace": {"otra": "convencion"}}
    db.commit()
    assert scm.MARGIN_OF_SAFETY not in scm.context_metrics_with_data(db)


def test_contexto_nivel_dca(db, monkeypatch):
    db.execute(sa.text(
        "INSERT INTO dca_signal_states (tenant_id, symbol, company_id, level, status, period,"
        " signal_date, close, metrics, level_prices, sources, params_version, evaluated_at,"
        " data_source, created_at, updated_at)"
        " VALUES (1, 'C1', NULL, 3, 'ok', 'swing', '2026-10-31', 10, '{}', '{}', '{}',"
        " 'v1', '2026-10-31', 'x', '2026-10-31', '2026-10-31')"
    ))
    db.commit()
    assert scm.DCA_LEVEL in scm.context_metrics_with_data(db)
    # Sin filas (motor sin senales): no se ofrece.
    db.execute(sa.text("DELETE FROM dca_signal_states"))
    db.commit()
    assert scm.DCA_LEVEL not in scm.context_metrics_with_data(db)


def test_facts_distinct_mismo_conjunto(db):
    now = datetime.now(UTC)
    db.add_all([
        _fact(1, 1, "SEC", now, metric="sales"), _fact(1, 1, "SEC", now, metric="ebit"),
        _fact(2, 1, "ESEF", now, metric="sales"), _fact(3, 2, "SEC", now, metric="otra_tenant"),
    ])
    db.info.pop("tenant_id")
    db.commit()
    db.info["tenant_id"] = 1
    cobertura = ScreenerService()._metric_coverage_uncached(db)
    assert "sales" in cobertura and "ebit" in cobertura
    assert "otra_tenant" not in cobertura  # tenant 2 no se cuela


def test_distinct_fact_metrics_keeps_tenant_on_seed_and_recursive_steps(db):
    """An interleaved other tenant must not seed or leak into later probes."""
    from app.services.screener_service import _distinct_facts_metrics

    now = datetime.now(UTC)
    db.info.pop("tenant_id")
    for tenant, names in ((1, ("bbb", "ddd")), (2, ("aaa", "ccc", "eee"))):
        for name in names:
            db.add(_fact(1, tenant, "SEC", now, metric=name))
    db.commit()
    for tenant, expected in ((1, ["bbb", "ddd"]), (2, ["aaa", "ccc", "eee"]), (3, [])):
        db.info["tenant_id"] = tenant
        assert _distinct_facts_metrics(db) == expected


def test_calculated_distinct_probes_preserve_filters_and_tenant(db):
    from app.models import CalculatedMetric
    from app.services.screener_service import _distinct_calculated_metrics

    db.info.pop("tenant_id")
    for tenant, metric, value, status in (
        (1, "bbb", 1, "ok"), (1, "bbb", 2, "ok"),
        (1, "ddd", 3, "ok"), (1, "null_value", None, "ok"),
        (1, "bad_status", 4, "error"),
        (2, "aaa", 1, "ok"), (2, "ccc", 2, "ok"), (2, "eee", 3, "ok"),
    ):
        db.add(CalculatedMetric(tenant_id=tenant, company_id=1, metric=metric,
            value=value, status=status, period=f"p{tenant}-{metric}-{value}",
            definition_version=1, formula="1"))
    db.commit()
    statements = _contador(db.get_bind())
    for tenant, expected in ((1, ["bbb", "ddd"]), (2, ["aaa", "ccc", "eee"]), (3, [])):
        db.info["tenant_id"] = tenant
        assert _distinct_calculated_metrics(db) == expected
    assert len(statements) == 3
    assert all("WITH RECURSIVE" in query for query in statements)
    db.info.pop("tenant_id")
    assert set(_distinct_calculated_metrics(db)) == {"aaa", "bbb", "ccc", "ddd", "eee"}


def test_margin_existence_projects_only_required_payload_values(db):
    _montar_empresas_valoradas(db, 3)
    statements = _contador(db.get_bind())
    assert scm._any_margin_of_safety(db)
    assert len(statements) == 2
    assert all("calculation_trace" not in statement for statement in statements)
    outputs = next(statement for statement in statements if "FROM valuation_outputs" in statement)
    assert "JSON_EXTRACT" in outputs
    assert "valuation_outputs.equity_value" not in outputs


@pytest.mark.parametrize("margin", [None, True, "NaN", "Infinity", "not-a-number", {}, []])
def test_margin_existence_preserves_invalid_value_rejection(db, margin):
    models = _montar_empresas_valoradas(db, 1)
    out = db.scalar(sa.select(ValuationOutput).where(ValuationOutput.valuation_model_id == models[0].id))
    out.output_payload = {"margin_of_safety": margin, "trace": {
        "margin_of_safety_convention": "discount_to_value_v1"}}
    db.commit()
    assert not scm._any_margin_of_safety(db)


def test_bounded_pair_counts_equal_groupby_for_all_integer_ids(db):
    from app.models import Document
    from app.services.data_health_service import _coverage_groups

    now = datetime.now(UTC)
    db.info.pop("tenant_id")
    db.add_all([Company(id=i, ticker=f"NEG{i}", name="Boundary", exchange="X",
        currency="EUR", company_type="mature", valuation_model="dcf")
        for i in (-2147483648, -1, 0)])
    db.flush()
    for cid in (-2147483648, -1, 0, 1, 2):
        db.add(_fact(cid, 1, "SEC", now))
        db.add(_fact(cid, 1, "SEC", now - timedelta(days=1)))
        db.add(Document(company_id=cid, tenant_id=1, title="doc", source_type="SEC", updated_at=now))
    db.add(_fact(3, 2, "other", now))
    db.add(_fact(3, 1, "seed", now))
    db.commit()
    db.info["tenant_id"] = 1
    inventory_rows = inventory(db, now=now)["sources"]
    for table, column, layer, reported in (
        ("financial_facts", "source_type", "Fundamentales", True),
        ("documents", "source_type", "Documentos", False),
        ("news_events", "source", "Noticias", False),
        ("market_prices", "source", "Precios diarios", False),
    ):
        actual = _coverage_groups(db, table=table, source_col=column, tenant=1,
            reported=reported, prices=table == "market_prices")
        expected = [(r["source"], r["covered"]) for r in inventory_rows
            if r["layer"] == layer and r["source"] is not None]
        assert sorted((src, count) for src, count, stamp in actual) == sorted(expected)
        for src, count, stamp in actual:
            assert stamp == now.replace(tzinfo=None)


def test_postgres_inventory_uses_bounded_probes_and_matches_portable_result(db, monkeypatch):
    now = datetime.now(UTC)
    db.add(_fact(1, 1, "SEC", now))
    db.add(NewsEvent(company_id=1, tenant_id=1, title="news", source="rss", updated_at=now))
    db.commit()
    portable = inventory(db, now=now)
    statements = _contador(db.get_bind())
    monkeypatch.setattr(db.get_bind().dialect, "name", "postgresql")
    bounded = inventory(db, now=now)
    assert bounded == portable
    recursive = [statement for statement in statements if "WITH RECURSIVE" in statement]
    assert len(recursive) == 3
    assert all("company_id >= -2147483648" in statement for statement in recursive)
    assert all("tenant_id = ?" in statement for statement in recursive if "FROM market_prices" not in statement)
