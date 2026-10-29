"""Reconstrucción idempotente de la serie de snapshots y su cadena TWR.

Contexto: las fotos diarias solo valoran un día si las posiciones se
importaron ese día; cuando una foto a mitad de serie quedó incompleta, la
cadena TWR no se reinicia por diseño ("la serie está rota y no se
reinicia", PortfolioSnapshotService) y las bandas de Factores quedan
SIN DATOS. Esta herramienta reconstruye la serie desde datos fechados
(libro de operaciones × cierres × FX, ver PortfolioReconstructionService)
y la escribe con procedencia y alcance declarados.

Reglas:
- Nunca escribe sin reconstrucción verificada (status "ok": cantidades
  iniciales no negativas y valor final dentro del 3 % del guardado).
- Idempotente: borra y recrea las fotos del rango reconstruido; una
  segunda ejecución produce el mismo contenido.
- Toda escritura exige backup previo en JSON y existe restauración con
  restore_backup(). El plan de backup/restore operativo vive en el
  docstring del script scripts/rebuild_portfolio_twr_snapshots.py.
- Alcance declarado: SOLO posiciones (sin caja, margen ni dividendos);
  cada foto lleva metadata["positions_only"] = True y capture() no
  encadena un día real sobre una foto reconstruida (mezclaría
  posiciones+caja con solo-posiciones): ese día queda bloqueado y marcado
  como nueva base ("twr_base_after_scope_change").
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CashDailySnapshot,
    PortfolioDailySnapshot,
    PositionDailySnapshot,
)
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.portfolio_reconstruction_service import (
    METHOD,
    SCOPE,
    PortfolioReconstructionService,
)

REBUILD_SOURCE = "twr_rebuild"
TOOL_VERSION = "1"


def _child_rows(db: Session, snapshot_ids: list[int]) -> dict[str, list[dict[str, Any]]]:
    cash = (
        [
            {
                "portfolio_id": row.portfolio_id,
                "snapshot_date": row.snapshot_date.isoformat(),
                "currency": row.currency,
                "balance_native": str(row.balance_native),
                "fx_rate": str(row.fx_rate),
                "balance_base": str(row.balance_base),
                "source": row.source,
            }
            for row in db.scalars(
                select(CashDailySnapshot).where(CashDailySnapshot.portfolio_snapshot_id.in_(snapshot_ids))
            ).all()
        ]
        if snapshot_ids
        else []
    )
    positions = (
        [
            {
                "portfolio_id": row.portfolio_id,
                "company_id": row.company_id,
                "snapshot_date": row.snapshot_date.isoformat(),
                "quantity": str(row.quantity),
                "market_price_native": str(row.market_price_native),
                "currency": row.currency,
                "fx_rate": None if row.fx_rate is None else str(row.fx_rate),
                "market_value_native": str(row.market_value_native),
                "market_value_base": None if row.market_value_base is None else str(row.market_value_base),
            }
            for row in db.scalars(
                select(PositionDailySnapshot).where(
                    PositionDailySnapshot.portfolio_snapshot_id.in_(snapshot_ids)
                )
            ).all()
        ]
        if snapshot_ids
        else []
    )
    return {"cash": cash, "positions": positions}


def _snapshot_to_dict(row: PortfolioDailySnapshot) -> dict[str, Any]:
    return {
        "portfolio_id": row.portfolio_id,
        "snapshot_date": row.snapshot_date.isoformat(),
        "base_currency": row.base_currency,
        "positions_value_base": str(row.positions_value_base),
        "cash_value_base": str(row.cash_value_base),
        "total_value_base": str(row.total_value_base),
        "net_external_flow_base": str(row.net_external_flow_base),
        "daily_return": None if row.daily_return is None else str(row.daily_return),
        "cumulative_twr": None if row.cumulative_twr is None else str(row.cumulative_twr),
        "pricing_coverage": str(row.pricing_coverage),
        "source": row.source,
        "metadata": row.metadata_ or {},
    }


class TwrRebuildService:
    """Reconstruye la serie de fotos diarias de la cartera por defecto."""

    def plan(self, db: Session, *, start: date | None = None) -> dict[str, Any]:
        """Dry-run: qué se reconstruiría y qué se reemplazaría. No escribe."""
        fx = PortfolioFXService()
        portfolio = fx.portfolio(db)
        if portfolio is None:
            return {"status": "no_portfolio", "writes": 0}
        rec = PortfolioReconstructionService().build(db, start=start)
        plan: dict[str, Any] = {
            "status": rec.status,
            "portfolio_id": portfolio.id,
            "method": METHOD,
            "scope": SCOPE,
            "reconstruction": rec.as_dict(),
            "writes": 0,
        }
        if rec.status != "ok" or not rec.series:
            # Sin verificación de valor final no se toca nada: la herramienta
            # nunca sustituye datos existentes por una serie no validada.
            plan["reason"] = (
                "reconstruction_not_verified: se requiere status 'ok' "
                "(cantidades no negativas y valor final dentro del 3 %)"
            )
            return plan
        first, last = rec.series[0]["date"], rec.series[-1]["date"]
        existing = list(
            db.scalars(
                select(PortfolioDailySnapshot)
                .where(
                    PortfolioDailySnapshot.portfolio_id == portfolio.id,
                    PortfolioDailySnapshot.snapshot_date >= date.fromisoformat(first),
                    PortfolioDailySnapshot.snapshot_date <= date.fromisoformat(last),
                )
                .order_by(PortfolioDailySnapshot.snapshot_date)
            ).all()
        )
        plan.update(
            {
                "range": {"first": first, "last": last},
                "existing_snapshots_in_range": len(existing),
                "existing_dates": [row.snapshot_date.isoformat() for row in existing],
                "existing_sources": sorted({row.source for row in existing}),
                "rows_to_insert": len(rec.series),
                "returns_linked": len(rec.returns),
                "preview": rec.series[:3]
                + ([{"...": "..."}] if len(rec.series) > 6 else [])
                + rec.series[-3:],
            }
        )
        return plan

    def apply(self, db: Session, *, backup_path: str | Path, start: date | None = None) -> dict[str, Any]:
        """Backup + reemplazo atómico de las fotos del rango reconstruido."""
        plan = self.plan(db, start=start)
        if plan.get("status") != "ok" or not plan.get("range"):
            return {**plan, "applied": False}
        portfolio_id: int = plan["portfolio_id"]
        first = date.fromisoformat(plan["range"]["first"])
        last = date.fromisoformat(plan["range"]["last"])

        existing = list(
            db.scalars(
                select(PortfolioDailySnapshot)
                .where(
                    PortfolioDailySnapshot.portfolio_id == portfolio_id,
                    PortfolioDailySnapshot.snapshot_date >= first,
                    PortfolioDailySnapshot.snapshot_date <= last,
                )
                .order_by(PortfolioDailySnapshot.snapshot_date)
            ).all()
        )
        ids = [row.id for row in existing]
        backup = {
            "tool": "twr_rebuild",
            "tool_version": TOOL_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "portfolio_id": portfolio_id,
            "range": plan["range"],
            "snapshots": [_snapshot_to_dict(row) for row in existing],
            "children": _child_rows(db, ids),
        }
        path = Path(backup_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(backup, indent=2, ensure_ascii=False), encoding="utf-8")

        for model in (PositionDailySnapshot, CashDailySnapshot):
            for row in (
                db.scalars(select(model).where(model.portfolio_snapshot_id.in_(ids))).all() if ids else []
            ):
                db.delete(row)
        for row in existing:
            db.delete(row)
        db.flush()

        rec = PortfolioReconstructionService().build(db, start=start)
        base = plan["reconstruction"]
        cumulative: Decimal | None = None
        inserted = 0
        for row in rec.series:
            day = date.fromisoformat(row["date"])
            value = Decimal(str(row["value_base"]))
            daily = rec.returns.get(day)
            if daily is not None:
                daily_dec = Decimal(str(daily))
                prior = cumulative if cumulative is not None else Decimal("0")
                cumulative = (Decimal("1") + prior) * (Decimal("1") + daily_dec) - Decimal("1")
            else:
                daily_dec = None
            db.add(
                PortfolioDailySnapshot(
                    portfolio_id=portfolio_id,
                    snapshot_date=day,
                    base_currency=PortfolioFXService().base_currency(db),
                    positions_value_base=value,
                    cash_value_base=Decimal("0"),
                    total_value_base=value,
                    net_external_flow_base=Decimal("0"),
                    daily_return=daily_dec,
                    cumulative_twr=cumulative if daily_dec is not None else None,
                    pricing_coverage=Decimal("1"),
                    source=REBUILD_SOURCE,
                    metadata_={
                        "method": METHOD,
                        "scope": SCOPE,
                        "positions_only": True,
                        "tool_version": TOOL_VERSION,
                        "interval": "since_previous_valued_day",
                        "flows": "trade_flows_embedded_in_return_at_close_fx_of_flow_date",
                        "end_value_check": base["price_check"].get("end_value_check"),
                        "excluded_days": base["excluded_days"],
                        "disclaimer": (
                            "Serie reconstruida solo con posiciones: sin caja, "
                            "margen ni dividendos. No comparable con fotos de "
                            "captura real; el primer capture() posterior no "
                            "encadena sobre ella (nueva base marcada)."
                        ),
                    },
                )
            )
            inserted += 1
        db.flush()
        return {
            **plan,
            "applied": True,
            "backup_path": str(path),
            "deleted_snapshots": len(existing),
            "inserted_snapshots": inserted,
        }

    def restore_backup(self, db: Session, *, backup_path: str | Path) -> dict[str, Any]:
        """Revierte un apply: repone las fotos del backup en su rango."""
        backup = json.loads(Path(backup_path).read_text(encoding="utf-8"))
        if backup.get("tool") != "twr_rebuild":
            return {"status": "not_a_twr_rebuild_backup", "restored": 0}
        portfolio_id = int(backup["portfolio_id"])
        first = date.fromisoformat(backup["range"]["first"])
        last = date.fromisoformat(backup["range"]["last"])
        current = list(
            db.scalars(
                select(PortfolioDailySnapshot).where(
                    PortfolioDailySnapshot.portfolio_id == portfolio_id,
                    PortfolioDailySnapshot.snapshot_date >= first,
                    PortfolioDailySnapshot.snapshot_date <= last,
                )
            ).all()
        )
        ids = [row.id for row in current]
        for model in (PositionDailySnapshot, CashDailySnapshot):
            for row in (
                db.scalars(select(model).where(model.portfolio_snapshot_id.in_(ids))).all() if ids else []
            ):
                db.delete(row)
        for row in current:
            db.delete(row)
        db.flush()
        restored = 0
        date_to_snapshot: dict[str, PortfolioDailySnapshot] = {}
        for item in backup["snapshots"]:
            snap = PortfolioDailySnapshot(
                portfolio_id=item["portfolio_id"],
                snapshot_date=date.fromisoformat(item["snapshot_date"]),
                base_currency=item["base_currency"],
                positions_value_base=Decimal(item["positions_value_base"]),
                cash_value_base=Decimal(item["cash_value_base"]),
                total_value_base=Decimal(item["total_value_base"]),
                net_external_flow_base=Decimal(item["net_external_flow_base"]),
                daily_return=None if item["daily_return"] is None else Decimal(item["daily_return"]),
                cumulative_twr=None if item["cumulative_twr"] is None else Decimal(item["cumulative_twr"]),
                pricing_coverage=Decimal(item["pricing_coverage"]),
                source=item["source"],
                metadata_=item["metadata"],
            )
            db.add(snap)
            date_to_snapshot[item["snapshot_date"]] = snap
            restored += 1
        db.flush()
        for cash in backup["children"]["cash"]:
            parent = date_to_snapshot.get(cash["snapshot_date"])
            if parent is None:
                continue
            db.add(
                CashDailySnapshot(
                    portfolio_snapshot_id=parent.id,
                    portfolio_id=cash["portfolio_id"],
                    snapshot_date=date.fromisoformat(cash["snapshot_date"]),
                    currency=cash["currency"],
                    balance_native=Decimal(cash["balance_native"]),
                    fx_rate=Decimal(cash["fx_rate"]),
                    balance_base=Decimal(cash["balance_base"]),
                    source=cash["source"],
                )
            )
        db.flush()
        for pos in backup["children"].get("positions", []):
            parent = date_to_snapshot.get(pos["snapshot_date"])
            if parent is None:
                continue
            db.add(
                PositionDailySnapshot(
                    portfolio_snapshot_id=parent.id,
                    portfolio_id=pos["portfolio_id"],
                    company_id=pos["company_id"],
                    snapshot_date=date.fromisoformat(pos["snapshot_date"]),
                    quantity=Decimal(pos["quantity"]),
                    market_price_native=Decimal(pos["market_price_native"]),
                    currency=pos["currency"],
                    fx_rate=None if pos["fx_rate"] is None else Decimal(pos["fx_rate"]),
                    market_value_native=Decimal(pos["market_value_native"]),
                    market_value_base=None
                    if pos["market_value_base"] is None
                    else Decimal(pos["market_value_base"]),
                )
            )
        db.flush()
        return {"status": "restored", "restored": restored, "deleted": len(current)}
