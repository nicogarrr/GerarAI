from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CashBalance, Company, Position
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.provenance import Coverage, SourceKind, provenance
from app.valuation import calculate_portfolio_risk


class RiskService:
    def dashboard(self, db: Session) -> dict:
        fx = PortfolioFXService()
        base_currency = fx.base_currency(db)
        missing_fx: list[dict] = []
        rows = db.execute(select(Position, Company).join(Company, Position.company_id == Company.id)).all()
        positions = []
        for position, company in rows:
            value_base = position.market_value_base
            if value_base is None and position.currency == base_currency:
                value_base = position.market_value_native or position.market_value
            if value_base is None:
                missing_fx.append(
                    {
                        "kind": "position",
                        "ticker": company.ticker,
                        "quote_currency": position.currency,
                        "base_currency": base_currency,
                        "as_of": position.as_of.isoformat(),
                    }
                )
                continue
            positions.append({
                "ticker": company.ticker,
                "name": company.name,
                "sector": company.sector,
                "factor_tags": company.factor_tags,
                "market_value": value_base,
                "market_price": position.market_price,
                "unrealized_pnl": position.unrealized_pnl_base,
                "as_of": position.as_of.isoformat() if position.as_of else None,
            })
        cash_native: dict[str, float] = {}
        cash_base = 0.0
        cash_assets_base = 0.0
        margin_debt_base = 0.0
        cash_rows = list(db.scalars(select(CashBalance)).all())
        cash_table = fx.fx_table(
            db,
            currencies={row.currency for row in cash_rows},
            base_currency=base_currency,
            as_of_max=max((row.as_of for row in cash_rows), default=None) or date.today(),
        ) if cash_rows else {}
        for row in cash_rows:
            cash_native[row.currency] = cash_native.get(row.currency, 0.0) + float(row.balance)
            rate = PortfolioFXService.rate_from_table(
                cash_table,
                quote_currency=row.currency,
                base_currency=base_currency,
                as_of=row.as_of,
            )
            if rate is None:
                missing_fx.append(
                    {
                        "kind": "cash",
                        "quote_currency": row.currency,
                        "base_currency": base_currency,
                        "as_of": row.as_of.isoformat(),
                    }
                )
                continue
            converted = float(row.balance * rate)
            cash_base += converted
            cash_assets_base += max(converted, 0.0)
            margin_debt_base += max(-converted, 0.0)
        result = calculate_portfolio_risk(
            positions,
            [{"currency": base_currency, "balance": cash_base, "net_of": cash_native}],
        )
        result.update(
            {
                "status": "incomplete_fx" if missing_fx else "ok",
                "base_currency": base_currency,
                "cash_native": cash_native,
                "cash_assets_base": cash_assets_base,
                "margin_debt_base": margin_debt_base,
                "missing_fx": missing_fx,
            }
        )
        result["trace"] = {
            "method": "portfolio_risk_snapshot_fx_v2",
            "fx_policy": "quote amount multiplied by latest rate on or before as_of",
            "excluded_for_missing_fx": len(missing_fx),
        }
        position_dates = [p["as_of"] for p in positions if p.get("as_of")]
        result["data_as_of"] = min(position_dates) if position_dates else None
        result["provenance"] = provenance(
            "Base de datos de GerarAI",
            SourceKind.INTERNAL,
            coverage=Coverage.PARTIAL if missing_fx else Coverage.OK,
            note="Calculado desde posiciones/precios/FX persistidos; cada fila upstream lleva su propia procedencia.",
        )
        return result
