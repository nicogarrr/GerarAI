"""Recalcula metricas/WACC y persiste un valuation_model nuevo por empresa.

No llama a ningun LLM ni regenera tesis: solo MetricCalculationService
(persist) y ValuationService (value_company + persist_output). Las filas de
valuation_models solo se escribian al generar una tesis; tras una reingesta
quedaban con el estado anterior aunque el WACC ya fuera trazable.

Uso:
    python scripts/recompute_valuation_models.py --tenant-external-id <ext> [--tickers AMD AVGO] [--limit N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Company, Tenant
from app.services.metric_calculation_service import MetricCalculationService
from app.services.valuation_service import ValuationService


def recompute_company(db, company: Company) -> dict:
    MetricCalculationService().calculate_all(db, company, persist=True)
    service = ValuationService()
    valuation = service.value_company(db, company)
    model = service.persist_output(db, company, valuation)
    return {
        "ticker": company.ticker,
        "status": model.status if model else None,
        "model_type": valuation.get("model_type"),
        "missing_inputs": valuation.get("missing_inputs") or [],
        "publication_blockers": valuation.get("publication_blockers") or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-external-id", required=True)
    parser.add_argument("--tickers", nargs="*", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    db = SessionLocal()
    counts: dict[str, int] = {}
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.external_id == args.tenant_external_id))
        if tenant is None:
            print(f"Tenant no encontrado: {args.tenant_external_id}")
            return 1
        db.info["tenant_id"] = tenant.id
        query = select(Company).order_by(Company.ticker)
        if args.tickers:
            query = query.where(Company.ticker.in_([t.upper() for t in args.tickers]))
        companies = list(db.scalars(query).all())
        if args.limit:
            companies = companies[: args.limit]
        for company in companies:
            try:
                row = recompute_company(db, company)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                print(f"ERROR {company.ticker}: {str(exc)[:160]}")
                counts["error"] = counts.get("error", 0) + 1
                continue
            counts[row["status"] or "none"] = counts.get(row["status"] or "none", 0) + 1
            print(
                f"{row['ticker']}: {row['status']} {row['model_type']} "
                f"missing={row['missing_inputs']} blockers={row['publication_blockers']}"
            )
    finally:
        db.close()
    print("RESULTADO:", counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
