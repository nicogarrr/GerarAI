from collections import defaultdict
from decimal import Decimal
from typing import Any


def _to_float(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value or 0)


def calculate_portfolio_risk(positions: list[dict], cash: list[dict]) -> dict:
    equity_value = sum(_to_float(position["market_value"]) for position in positions)
    cash_by_currency = {item["currency"]: _to_float(item["balance"]) for item in cash}
    total_value = equity_value + sum(cash_by_currency.values())
    # Con caja neta negativa (margen) el total es menor que la cartera y los pesos
    # superaban el 100 % (173 %). Entonces se pesa sobre el valor bruto de las
    # posiciones, que es la base de la tabla de Cartera.
    gross_basis = sum(cash_by_currency.values()) < 0 and equity_value > 0
    weight_base = equity_value if gross_basis else total_value

    sector_exposure = defaultdict(float)
    factor_exposure = defaultdict(float)
    position_rows = []
    alerts = []

    for position in positions:
        value = _to_float(position["market_value"])
        weight = value / weight_base if weight_base else 0
        sector_exposure[position["sector"]] += weight
        for tag in position.get("factor_tags", []):
            factor_exposure[tag] += weight
        position_rows.append({**position, "weight": weight})

        if weight > 0.20:
            alerts.append(
                {
                    "severity": "high",
                    "ticker": position["ticker"],
                    "message": f"{position['ticker']} supera el 20 % de peso en la cartera",
                    "metric_value": weight,
                    "threshold": 0.20,
                }
            )
        if "pre_fcf" in position.get("factor_tags", []) and weight > 0.10:
            alerts.append(
                {
                    "severity": "medium",
                    "ticker": position["ticker"],
                    "message": f"{position['ticker']} es pre-FCF y supera el 10 % de peso en la cartera",
                    "metric_value": weight,
                    "threshold": 0.10,
                }
            )

    net_items = {item["currency"]: item for item in cash if item.get("net_of")}
    for currency, balance in cash_by_currency.items():
        if balance < 0:
            net = net_items.get(currency)
            if net:
                negative = ", ".join(
                    f"{cur} ({amount:,.2f})" for cur, amount in sorted(net["net_of"].items()) if amount < 0
                )
                message = f"El saldo neto de caja, convertido a {currency}, es negativo"
                if negative:
                    message += f" (saldo negativo en {negative})"
            else:
                message = f"El saldo de caja en {currency} es negativo"
            alerts.append(
                {
                    "severity": "high",
                    "ticker": None,
                    "message": message,
                    "metric_value": balance,
                    "threshold": 0,
                }
            )

    sorted_positions = sorted(position_rows, key=lambda row: row["weight"], reverse=True)
    top_1 = sorted_positions[0]["weight"] if sorted_positions else 0
    top_5 = sum(row["weight"] for row in sorted_positions[:5])

    return {
        "total_value": total_value,
        "weight_basis": "gross_equity" if gross_basis else "total_with_cash",
        "equity_value": equity_value,
        "cash": cash_by_currency,
        "top_1_weight": top_1,
        "top_5_weight": top_5,
        "positions": sorted_positions,
        "sector_exposure": dict(sorted(sector_exposure.items())),
        "factor_exposure": dict(sorted(factor_exposure.items())),
        "alerts": alerts,
        "trace": {"method": "portfolio_risk_snapshot"},
    }

