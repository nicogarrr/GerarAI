"""Graba los fixtures de regresión de la batería de 7 (SOLO LECTURA en prod).

Uso en la VM (sin escrituras; abre SessionLocal solo para SELECT):

    python scripts/record_battery_fixtures.py --tenant-external-id <ext> \
        [--tickers UBER CHTR UNH BFIT.AS ASTS PLTR TSLA] \
        [--out tests/fixtures/valuation/battery7]

Por cada ticker:
1. Lee company + financial_facts + último market_price + calculated_metrics
   (datos de mercado; NUNCA tenant, inputs declarados, tesis ni usuarios).
2. Reconstruye un sqlite en memoria con el MISMO loader que el test
   (tests.test_battery7_regression.load_fixture_into_session) y corre el
   motor que enruta el registry — así la salida grabada es reproducible bit
   a bit por tests/test_battery7_regression.py sin tocar la red ni la BD.
3. Escribe <TICKER>.json con entradas + salida completa + SHA de git en
   curso (FAV del auditor por SHA) y el SHA queda en meta.recorded_sha.

Si la salida aislada difiere de la que prod publicó por inputs privados del
usuario, es a propósito: los fixtures no llevan datos personales y la red de
regresión cubre los motores sobre datos de mercado públicos.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    CalculatedMetric,
    Company,
    FinancialFact,
    MarketPrice,
    Tenant,
)
from tests.test_battery7_regression import (
    _default,
    company_to_dict,
)

BATTERY7 = ["UBER", "CHTR", "UNH", "BFIT.AS", "ASTS", "PLTR", "TSLA"]


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unknown"


def _dump_facts(db, company: Company, tenant: Tenant) -> list[dict]:
    rows = db.scalars(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.tenant_id == tenant.id,
        )
    ).all()
    return [
        {
            "_id": r.id,
            "metric": r.metric,
            "value": str(r.value),
            "unit": r.unit,
            "period": r.period,
            "fiscal_year": r.fiscal_year,
            "fiscal_quarter": r.fiscal_quarter,
            "source_type": r.source_type,
            "is_reported": r.is_reported,
            "is_adjusted": r.is_adjusted,
            "confidence": str(r.confidence),
            "accession_number": r.accession_number,
            "filed": r.filed.isoformat() if r.filed else None,
        }
        for r in rows
    ]


def _dump_price(db, company: Company) -> dict | None:
    r = db.scalar(
        select(MarketPrice)
        .where(MarketPrice.company_id == company.id)
        .order_by(MarketPrice.date.desc())
        .limit(1)
    )
    if r is None:
        return None
    return {
        "date": r.date.isoformat(),
        "open": str(r.open),
        "high": str(r.high),
        "low": str(r.low),
        "close": str(r.close),
        "adj_close": str(r.adj_close) if r.adj_close is not None else None,
        "volume": r.volume,
        "quote_currency": r.quote_currency,
        "source": r.source,
    }


def _dump_calculated(db, company: Company, tenant: Tenant) -> list[dict]:
    rows = db.scalars(
        select(CalculatedMetric).where(
            CalculatedMetric.company_id == company.id,
            CalculatedMetric.tenant_id == tenant.id,
        )
    ).all()
    return [
        {
            "metric": r.metric,
            "value": str(r.value) if r.value is not None else None,
            "unit": r.unit,
            "period": r.period,
            "fiscal_year": r.fiscal_year,
            "fiscal_quarter": r.fiscal_quarter,
            "status": r.status,
            "definition_version": r.definition_version,
            "formula": r.formula,
            "numerator": str(r.numerator) if r.numerator is not None else None,
            "denominator": str(r.denominator) if r.denominator is not None else None,
            "source_fact_ids": list(r.source_fact_ids or []),
            "calculation_trace": r.calculation_trace or {},
            "confidence": str(r.confidence),
        }
        for r in rows
    ]


def record_ticker(ticker: str, tenant: Tenant, out_dir: Path, sha: str) -> dict:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models.entities import Base
    from app.valuation.engines.registry import resolve_engine_key
    from tests.test_battery7_regression import run_fixture

    prod = SessionLocal()
    try:
        company = prod.scalar(select(Company).where(Company.ticker == ticker).order_by(Company.id))
        if company is None:
            return {"ticker": ticker, "recorded": False, "reason": "no existe en la BD"}
        fixture = {
            "meta": {
                "ticker": ticker,
                "recorded_sha": sha,
                "recorded_at": date.today().isoformat(),
                "engine_key": resolve_engine_key(company),
                "note": "grabado aislado, sin inputs privados del tenant",
            },
            "company": company_to_dict(company),
            "facts": _dump_facts(prod, company, tenant),
            "price": _dump_price(prod, company),
            "calculated_metrics": _dump_calculated(prod, company, tenant),
        }
        if fixture["price"] is None:
            return {"ticker": ticker, "recorded": False, "reason": "sin market_price"}
    finally:
        prod.close()

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        output = run_fixture(session, fixture)
    fixture["output"] = json.loads(json.dumps(output, default=_default))

    path = out_dir / f"{ticker.replace('/', '_')}.json"
    path.write_text(
        json.dumps(fixture, default=_default, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    status = fixture["output"].get("status")
    return {
        "ticker": ticker,
        "recorded": True,
        "engine": fixture["meta"]["engine_key"],
        "status": status,
        "fixture": str(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant-external-id",
        required=True,
        help="Solo para localizar las filas; nunca se graba en los fixtures.",
    )
    parser.add_argument("--tickers", nargs="*", default=BATTERY7)
    parser.add_argument("--out", default="tests/fixtures/valuation/battery7")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    sha = _git_sha()
    prod = SessionLocal()
    try:
        tenant = prod.scalar(select(Tenant).where(Tenant.external_id == args.tenant_external_id))
        if tenant is None:
            print(json.dumps({"recorded": False, "reason": "tenant desconocido"}, ensure_ascii=False))
            return 1
        results = [record_ticker(t, tenant, out_dir, sha) for t in args.tickers]
    finally:
        prod.close()
    for r in results:
        print(json.dumps(r, ensure_ascii=False))
    return 0 if any(r["recorded"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
