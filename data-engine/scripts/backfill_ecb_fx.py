"""Descarga los tipos de cambio oficiales del BCE para las fechas del libro.

El informe fiscal (IRPF) convierte cada compra y cada venta al tipo de su
propia fecha. Este script rellena ``fx_rates`` con la serie diaria del BCE
para todas las divisas que aparecen en las operaciones del tenant, desde la
primera operación (o ``--desde``) hasta el 31/12 del ejercicio pedido.

Uso:
    python scripts/backfill_ecb_fx.py --tenant-external-id <ext> --ejercicio 2025
    python scripts/backfill_ecb_fx.py --tenant-external-id <ext> --desde 2019-01-01 --hasta 2025-12-31
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models import Tenant, Transaction
from app.services.connectors.ecb_history import backfill_ecb_rates


async def _run(args) -> dict:
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.external_id == args.tenant_external_id))
        if tenant is None:
            print(f"Tenant no encontrado: {args.tenant_external_id}")
            return {}
        db.info["tenant_id"] = tenant.id
        currencies = {
            c for c in db.scalars(select(Transaction.currency).distinct()).all() if c
        }
        first = db.scalar(select(func.min(Transaction.trade_date)))
        start = date.fromisoformat(args.desde) if args.desde else (first or date(args.ejercicio, 1, 1))
        end = date.fromisoformat(args.hasta) if args.hasta else date(args.ejercicio, 12, 31)
        print(f"Divisas: {sorted(currencies)} · rango {start} → {end}")
        return await backfill_ecb_rates(db, currencies=currencies, start=start, end=end)
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-external-id", required=True)
    parser.add_argument("--ejercicio", type=int, default=date.today().year - 1)
    parser.add_argument("--desde", default=None, help="AAAA-MM-DD (por defecto, la primera operación)")
    parser.add_argument("--hasta", default=None, help="AAAA-MM-DD (por defecto, 31/12 del ejercicio)")
    args = parser.parse_args()
    print("RESULTADO:", asyncio.run(_run(args)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
