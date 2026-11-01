"""Perf changes-since: «qué ha cambiado» por métrica con N consultas constantes.

Antes: 1 + hasta 2 consultas SQL por métrica con datos nuevos (40 métricas
tras una ingesta = 121 consultas por petición). Ahora: 2 consultas en total
(una para los datos nuevos y otra para el histórico de esas métricas), con la
misma salida (mismo ORDER BY created_at DESC, id DESC y desempate por id).
Medido en este test: 40 métricas x (1 nueva + 2 históricas)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact
from app.services.company_changes_service import changes_since

SINCE = datetime(2026, 10, 1, tzinfo=UTC)


def _fact(db, company, metric, value, period, when, source="sec_xbrl"):
    db.add(
        FinancialFact(
            company_id=company.id,
            metric=metric,
            value=Decimal(value),
            unit="USD",
            period=period,
            source_type=source,
            created_at=when,
            updated_at=when,
        )
    )


def _setup():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    company = Company(
        ticker="CHGN",
        name="Change N Co",
        exchange="NASDAQ",
        currency="USD",
        sector="T",
        industry="T",
        company_type="stock",
        valuation_model="dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    before, older = datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 6, 1, tzinfo=UTC)
    after = datetime(2026, 10, 15, tzinfo=UTC)
    for i in range(40):
        m = f"metric_{i:02d}"
        _fact(db, company, m, "100", "FY2025", before)  # revisión del mismo periodo
        _fact(db, company, m, "90", "FY2024", older)  # histórico de otro periodo
        _fact(db, company, m, "104", "FY2025", after)  # dato nuevo
    db.commit()
    return engine, db, company


def test_metric_changes_usa_consultas_constantes():
    engine, db, company = _setup()
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def _cuenta(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    # _metric_changes directo con 40 métricas (la vía web las capa a
    # MAX_ITEMS=8): antes 1 + hasta 2 consultas por métrica = 121; ahora 2.
    from app.services.company_changes_service import _metric_changes

    metrics = [f"metric_{i:02d}" for i in range(40)]
    out = _metric_changes(db, company.id, SINCE, metrics)
    n_metric = len(statements)
    out2 = changes_since(db, company.id, SINCE)
    event.remove(engine, "before_cursor_execute", _cuenta)
    assert len(out) == 40
    # 2 propias (nuevos + histórico) + 1 constante de resolución de tenant
    # cuando la sesión no lo fija; sin el arreglo eran 121 para 40 métricas.
    assert n_metric <= 3, f"_metric_changes: {n_metric} consultas (N+1 por métrica)"
    # changes_since entero (docs + hechos + tesis + métricas, métricas capadas
    # a 8): sin el arreglo eran 4 + 25.
    assert len(out2["cambios_metricas"]) == 8
    assert len(statements) <= 12, f"{len(statements)} consultas (N+1 por métrica)"
    db.close()


def test_metric_changes_misma_salida_que_el_top1_por_metrica():
    engine, db, company = _setup()
    out = changes_since(db, company.id, SINCE)
    by_metric = {c["metric"]: c for c in out["cambios_metricas"]}
    # revisión del mismo periodo: anterior es el valor FY2025 previo, no el FY2024
    assert by_metric["metric_00"]["anterior"]["valor"] == 100.0
    assert by_metric["metric_00"]["anterior"]["periodo"] == "FY2025"
    assert by_metric["metric_00"]["nuevo"]["valor"] == 104.0
    assert by_metric["metric_00"]["fuente"] == "sec_xbrl"
    db.close()
