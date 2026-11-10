"""Filtro SQL explícito de caché aislado de la defensa ORM global."""

from datetime import UTC, date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, CalculatedMetric, Company, Tenant
from app.services import valuation_metrics_service as svc


class _UnscopedReadSession(Session):
    def scalars(self, statement, *args, **kwargs):
        # Simula una lectura de worker con bypass ORM explícito. El WHERE del
        # servicio sigue ejecutándose en SQLite; no se retira ningún listener.
        return super().scalars(statement.execution_options(include_all_tenants=True), *args, **kwargs)


def test_cache_explicita_no_combina_metricas_de_dos_tenants(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    today = date(2026, 11, 9)
    try:
        with _UnscopedReadSession(engine) as db:
            db.add_all([Tenant(id=1, external_id="cache-t1"), Tenant(id=2, external_id="cache-t2")])
            company = Company(
                ticker="CACHE",
                name="Cache test",
                currency="USD",
                exchange="NASDAQ",
                company_type="operating",
                valuation_model="unassigned",
            )
            db.add(company)
            db.flush()
            # Cada tenant tiene SOLO una métrica. Sin WHERE explícito, el
            # agregado ve las dos y omite incorrectamente a la empresa.
            for tenant, metric in [(1, svc.METRIC_PB), (2, svc.METRIC_YIELD)]:
                db.info["tenant_id"] = tenant
                db.add(
                    CalculatedMetric(
                        tenant_id=tenant,
                        company_id=company.id,
                        metric=metric,
                        period=today.isoformat(),
                        definition_version=svc.METRIC_VERSION,
                        value=1,
                        formula="test",
                        updated_at=datetime.now(UTC),
                    )
                )
                db.commit()
            seen = []

            def compute(db_arg, companies, **kwargs):
                seen.extend(c.id for c in companies)
                return {"computed": len(companies)}

            monkeypatch.setattr(svc, "compute_valuation_metrics", compute)
            for tenant in (1, 2):
                db.info["tenant_id"] = tenant
                seen.clear()
                result = svc.refresh_valuation_metrics(db, as_of=today)
                assert result["companies_skipped_fresh_24h"] == 0
                assert result["computed"] == 1 and seen == [company.id]
    finally:
        engine.dispose()
