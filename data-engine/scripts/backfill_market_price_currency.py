"""Rellena ``market_prices.quote_currency`` NULL con la divisa REAL de Yahoo.

Uso:
    python scripts/backfill_market_price_currency.py --dry-run
    python scripts/backfill_market_price_currency.py --ticker MSFT --ticker GOOGL
    python scripts/backfill_market_price_currency.py --pause 1.5 --limit 50

Idempotente (solo filas NULL), por lotes (1 empresa = 1 llamada a Yahoo con
pausa) y NUNCA infiere la divisa: si Yahoo no la da, la fila queda NULL.
En prod: hacer backup antes; ejecutar SIN --dry-run solo tras revisar el
resumen en seco.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal
from app.services.connectors.yahoo import YahooFinanceClient
from app.services.market_price_currency_backfill import backfill_quote_currency


async def _run(args) -> dict:
    yahoo = YahooFinanceClient()

    async def fetch_currency(ticker: str) -> str | None:
        node = await yahoo.recent_daily_chart(ticker)  # range=5d: lo mínimo
        meta = node.get("meta") if isinstance(node, dict) else None
        currency = meta.get("currency") if isinstance(meta, dict) else None
        return currency if isinstance(currency, str) else None

    db = SessionLocal()
    try:
        return await backfill_quote_currency(
            db,
            fetch_currency=fetch_currency,
            dry_run=args.dry_run,
            pause_seconds=args.pause,
            company_limit=args.limit,
            tickers=args.ticker or None,
        )
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="cuenta sin escribir")
    parser.add_argument("--ticker", action="append", help="limita a estos tickers (repetible)")
    parser.add_argument("--pause", type=float, default=1.0, help="segundos entre llamadas a Yahoo")
    parser.add_argument("--limit", type=int, default=None, help="máximo de empresas por pasada")
    args = parser.parse_args()
    print("RESULTADO:", asyncio.run(_run(args)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
