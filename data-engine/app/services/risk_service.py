from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import CashBalance, Company, Position
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.provenance import Coverage, SourceKind, provenance
from app.valuation import calculate_portfolio_risk


class RiskService:
    def dashboard(self, db: Session) -> dict:
        fx = PortfolioFXService()
        base_currency = fx.base_currency(db)
        missing_fx: list[dict] = []
        held_valuation: list[dict] = []
        rows = db.execute(
            select(Position, Company)
            .join(Company, Position.company_id == Company.id)
            .options(joinedload(Position.company))
        ).all()
        positions = []
        fx_used: dict[tuple, dict] = {}
        for position, company in rows:
            if (
                position.currency
                and position.currency != base_currency
                and position.fx_rate is not None
                and position.as_of is not None
            ):
                fx_used[("positions", position.currency, float(position.fx_rate), position.as_of)] = {
                    "scope": "positions",
                    "currency": position.currency,
                    "rate": float(position.fx_rate),
                    "as_of": position.as_of.isoformat(),
                }
            if position.valuation_hold_reason:
                # Valoracion en suspenso: no entra con peso 0 ni con precio guardado;
                # queda declarada como excluida.
                held_valuation.append(
                    {
                        "ticker": company.ticker,
                        "reason": position.valuation_hold_reason,
                        "effective_date": position.valuation_hold_effective_date.isoformat()
                        if position.valuation_hold_effective_date
                        else None,
                    }
                )
                continue
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
            if row.currency != base_currency:
                fx_used[("cash", row.currency, float(rate), row.as_of)] = {
                    "scope": "cash",
                    "currency": row.currency,
                    "rate": float(rate),
                    "as_of": row.as_of.isoformat(),
                }
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
                "status": "incomplete_fx" if missing_fx else ("incomplete_valuation" if held_valuation else "ok"),
                "valuation_hold": held_valuation,
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
            "excluded_for_valuation_hold": len(held_valuation),
        }
        position_dates = [p["as_of"] for p in positions if p.get("as_of")]
        result["data_as_of"] = min(position_dates) if position_dates else None
        # Tipo y fecha de cada conversion a divisa base, y si caja y posiciones
        # se valoran en dias distintos (el total mezcla ambas fechas).
        cash_dates = sorted({row.as_of.isoformat() for row in cash_rows})
        result["cash_as_of"] = cash_dates[0] if cash_dates else None
        result["fx_rates"] = sorted(
            fx_used.values(), key=lambda item: (item["scope"], item["currency"], item["as_of"])
        )
        result["valuation_dates_differ"] = len(set(position_dates) | set(cash_dates)) > 1
        result["provenance"] = provenance(
            "Base de datos de GerarAI",
            SourceKind.INTERNAL,
            coverage=Coverage.PARTIAL if (missing_fx or held_valuation) else Coverage.OK,
            note="Calculado desde posiciones/precios/FX persistidos; cada fila upstream lleva su propia procedencia.",
        )
        return result
