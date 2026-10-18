"""Recalcula metricas derivadas (roe, margenes, roic, wacc...) en bulk.

Las CalculatedMetric solo se escribian on-demand al abrir una empresa, asi
que la cobertura del universo era ~cero (QA: "solo AAPL tenia roic") y los
screeners fundamentales no podian filtrar. Este script recorre las empresas
con financial_facts del tenant y persiste MetricCalculationService
(idempotente, upsert; sin hechos coherentes la metrica queda "unavailable",
nunca inventada). No llama a LLMs ni toca valuations: solo metricas.

Imprime cobertura por metrica ANTES y DESPUES para verificacion medible.

Uso (dentro del contenedor backend):
    python scripts/recompute_fundamental_metrics.py --tenant-external-id <ext> \
        [--tickers UNH AAPL] [--limit N] [--start-from TICKER]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from app.core.database import SessionLocal, init_db
from app.models import CalculatedMetric, Company, FinancialFact, Tenant
from app.services.metric_calculation_service import METRIC_DEFINITIONS, MetricCalculationService


def coverage(db) -> dict[str, int]:
    """Empresas con la metrica en estado ok (medible antes/despues)."""
    rows = db.execute(
        select(CalculatedMetric.metric, func.count(func.distinct(CalculatedMetric.company_id)))
        .where(CalculatedMetric.status == "ok")
        .group_by(CalculatedMetric.metric)
    ).all()
    return {metric: count for metric, count in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-external-id", required=True)
    parser.add_argument("--tickers", nargs="*", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start-from", default=None)
    args = parser.parse_args()
    init_db()
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.external_id == args.tenant_external_id))
        if tenant is None:
            print(f"Tenant no encontrado: {args.tenant_external_id}")
            return 1
        db.info["tenant_id"] = tenant.id
        before = coverage(db)
        with_facts = (
            select(FinancialFact.company_id)
            .where(FinancialFact.tenant_id == tenant.id)
            .distinct()
            .scalar_subquery()
        )
        query = select(Company).where(Company.id.in_(with_facts)).order_by(Company.ticker)
        if args.tickers:
            query = query.where(Company.ticker.in_([t.upper() for t in args.tickers]))
        if args.start_from:
            query = query.where(Company.ticker > args.start_from.upper())
        companies = list(db.scalars(query).all())
        if args.limit:
            companies = companies[: args.limit]
        service = MetricCalculationService()
        counts: dict[str, int] = {}
        errors = 0
        for index, company in enumerate(companies, start=1):
            try:
                results = service.calculate_all(db, company, persist=True)
                for result in results:
                    key = result.status or "unknown"
                    counts[key] = counts.get(key, 0) + 1
            except Exception as exc:  # noqa: BLE001 - una empresa no frena el barrido
                db.rollback()
                errors += 1
                print(f"ERROR {company.ticker}: {str(exc)[:160]}")
            if index % 100 == 0:
                print(f"[{index}/{len(companies)}] errores={errors}", flush=True)
        after = coverage(db)
        print("RESULTADO:", {"companies": len(companies), "metric_statuses": counts, "errors": errors})
        print("COBERTURA ANTES:", {m: before.get(m, 0) for m in sorted(METRIC_DEFINITIONS)})
        print("COBERTURA DESPUES:", {m: after.get(m, 0) for m in sorted(METRIC_DEFINITIONS)})
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
