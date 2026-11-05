"""Contexto real del consenso para el control de conciliación del DCF.

Adaptador sync entre los datos que ya existen (precios objetivo por analista y
supuestos de analista declarados) y ``app.valuation.consensus_sanity``. No
calcula nada por su cuenta ni inventa datos: el consenso agregado sale del
servicio de objetivos y los inputs del DCF, solo de filas ``method='analyst'``
con segmento de empresa entera. Nunca lanza hacia la tesis: un fallo del
consenso devuelve ``None`` y la conciliación sigue su curso.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from math import isfinite
from typing import Any

from sqlalchemy.orm import Session

from app.services.declared_input_service import DeclaredInputService
from app.valuation.consensus_sanity import DCF_INPUT_NAMES, StepLabel

#: Claves de ``declared_input_values`` que alimentan cada input del DCF.
_KEY_TO_DCF: dict[str, str] = {
    "revenue": "revenue",
    "revenue_growth": "growth",
    "growth": "growth",
    "fcf_margin": "margin",
    "margin": "margin",
    "wacc": "wacc",
    "terminal_growth": "terminal_growth",
    "net_debt": "net_debt",
    "shares_diluted": "shares_outstanding",
    "shares_outstanding": "shares_outstanding",
}
_RATE_KEYS = frozenset({"growth", "margin", "wacc", "terminal_growth"})


@dataclass(frozen=True)
class ConsensusSnapshot:
    """Consenso de analistas listo para el control (nunca inventado)."""

    symbol: str
    status: str  # available | empty | fetch_failed
    mean: float | None = None
    median: float | None = None
    low: float | None = None
    high: float | None = None
    currency: str | None = None
    source: str | None = None
    source_url: str | None = None
    fetched_at: int | None = None
    reference_price: float | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "mean": self.mean,
            "median": self.median,
            "low": self.low,
            "high": self.high,
            "currency": self.currency,
            "source": self.source,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
            "reference_price": self.reference_price,
            "rows": [dict(row) for row in self.rows],
        }


@dataclass(frozen=True)
class AnalystInputs:
    """Supuestos de analista en las unidades de la traza del DCF."""

    inputs: dict[str, Any] = field(default_factory=dict)
    labels: dict[str, StepLabel] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "inputs": dict(self.inputs),
            "labels": {
                key: {"label": value.label, "reason": value.reason}
                for key, value in self.labels.items()
            },
            "sources": dict(self.sources),
            "rows": [dict(row) for row in self.rows],
        }


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _target_row(raw: Any, currency: str | None) -> dict[str, Any]:
    when = _get(raw, "date")
    if when is None:
        when = _get(raw, "published_on")
    target = _get(raw, "target")
    if target is None:
        target = _get(raw, "price")
    if target is None:
        target = _get(raw, "price_target")
    return {
        "firm": _get(raw, "firm"),
        "date": _iso(when),
        "target": _finite(target),
        "currency": _get(raw, "currency") or currency,
    }


def _snapshot_from_targets(ticker: str, targets: Any) -> ConsensusSnapshot:
    consensus = _get(targets, "consensus")
    mean = _finite(_get(consensus, "mean"))
    median = _finite(_get(consensus, "median"))
    low = _finite(_get(consensus, "low"))
    high = _finite(_get(consensus, "high"))
    currency = _get(targets, "currency")
    if _get(targets, "note_code") == "fetch_failed":
        status = "fetch_failed"
    elif any(value is not None and value > 0 for value in (mean, median, low, high)):
        status = "available"
    else:
        status = "empty"
    symbol = _get(targets, "symbol") or ticker
    raw_rows = _get(targets, "rows") or []
    return ConsensusSnapshot(
        symbol=str(symbol),
        status=status,
        mean=mean,
        median=median,
        low=low,
        high=high,
        currency=str(currency) if currency else None,
        source=_get(targets, "source"),
        source_url=_get(targets, "source_url"),
        fetched_at=_int_or_none(_get(targets, "fetched_at")),
        reference_price=_finite(_get(targets, "reference_price")),
        rows=[_target_row(row, currency) for row in raw_rows],
    )


def load_consensus(
    db: Session,
    company: Any,
    *,
    loader: Callable[[str], Any] | None = None,
    timeout: float = 20.0,
) -> ConsensusSnapshot | None:
    """Consenso del valor; ``None`` si no hay ticker, no hay datos o algo falla.

    ``loader`` permite inyectar una fuente sync en tests (sin red). Por defecto
    se usa el servicio de objetivos por analista a través del puente sync.
    """
    ticker = _get(company, "ticker")
    if ticker is None or not str(ticker).strip():
        return None
    ticker = str(ticker).strip()
    try:
        if loader is not None:
            targets = loader(ticker)
        else:
            from app.services import analyst_targets_service as targets_module
            from app.services.async_bridge import run_from_any_context

            targets = run_from_any_context(
                targets_module.analyst_targets_service.get(ticker), timeout=timeout
            )
        if targets is None:
            return None
        return _snapshot_from_targets(ticker, targets)
    except Exception:  # noqa: BLE001 - el control nunca puede romper la tesis
        return None


def _rate(value: float, unit: str) -> float:
    normalized = (unit or "").lower()
    if "%" in normalized or "pct" in normalized or abs(value) > 1.5:
        return value / 100.0
    return value


def analyst_inputs_for_dcf(
    db: Session,
    company: Any,
    *,
    as_of: date | None = None,
) -> AnalystInputs:
    """Supuestos de analista vigentes, mapeados a las claves del DCF.

    Solo filas ``method='analyst'`` de la empresa entera (``segment_key=''``),
    válidas con las reglas actuales y no posteriores a ``as_of``. El valor es
    ``base``; las tasas se normalizan a decimal. Los rangos ``low``/``high``
    solo se explican en ``rows``: la cascada usa el valor base.
    """
    empty = AnalystInputs()
    info = (_get(db, "info", {}) or {}) if db is not None else {}
    tenant = info.get("tenant_id") if isinstance(info, Mapping) else None
    company_id = _get(company, "id")
    if type(tenant) is not int or tenant <= 0 or company_id is None:
        return empty

    service = DeclaredInputService()
    current = service.current(db, company_id=company_id, tenant_id=tenant)
    inputs: dict[str, Any] = {}
    labels: dict[str, StepLabel] = {}
    sources: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for (input_key, segment_key), row in current.items():
        if (segment_key or "") != "" or _get(row, "method") != "analyst":
            continue
        row_as_of = _get(row, "as_of")
        if as_of is not None and row_as_of is not None and row_as_of > as_of:
            continue
        dcf_key = _KEY_TO_DCF.get(input_key)
        if dcf_key is None or not service.row_is_valid(row):
            continue
        base = _finite(_get(row, "base"))
        if base is None:
            continue
        unit = str(_get(row, "unit") or "")
        low = _finite(_get(row, "low"))
        high = _finite(_get(row, "high"))
        value = _rate(base, unit) if dcf_key in _RATE_KEYS else base
        if dcf_key in _RATE_KEYS:
            if low is not None:
                low = _rate(low, unit)
            if high is not None:
                high = _rate(high, unit)
        firm = str(_get(row, "analyst_firm") or "").strip() or None
        source_url = str(_get(row, "source_url") or "").strip() or None
        if dcf_key not in inputs:
            inputs[dcf_key] = value
            labels[dcf_key] = (
                StepLabel("aceptamos", f"supuesto de {firm} con fuente")
                if firm
                else StepLabel("abierta", "supuesto de analista sin firma")
            )
            if source_url:
                sources[dcf_key] = source_url
        rows.append(
            {
                "input": dcf_key,
                "name": DCF_INPUT_NAMES.get(dcf_key, dcf_key),
                "value": value,
                "low": low,
                "high": high,
                "unit": unit,
                "status": _get(row, "status"),
                "method": _get(row, "method"),
                "analyst_firm": firm,
                "source_url": source_url,
                "source_quote": _get(row, "source_quote"),
                "as_of": _iso(row_as_of),
                "row_id": _get(row, "id"),
            }
        )
    return AnalystInputs(inputs=inputs, labels=labels, sources=sources, rows=rows)


__all__ = [
    "AnalystInputs",
    "ConsensusSnapshot",
    "analyst_inputs_for_dcf",
    "load_consensus",
]
