"""Clasificacion de company_type compartida (sin dependencias, evita ciclos)."""

# "portfolio_holding" / "imported_holding" significan «posicion que tengo en
# cartera», no «sociedad holding»: no deben activar el motor/marco de holdings.
POSITION_COMPANY_TYPES = frozenset({"portfolio_holding", "imported_holding"})


def is_holding_company_type(company_type: str | None) -> bool:
    value = (company_type or "").lower()
    return value not in POSITION_COMPANY_TYPES and ("holding" in value or "asset_manager" in value)
