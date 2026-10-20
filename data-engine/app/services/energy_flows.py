"""Electricity spending, not physical energy flows. EIA v2 retail-sales.

Verified live 2026-10-20: annual US revenue uses `million dollars`.
No price*volume estimates, no inferred company market shares. API key never
appears in returned URLs, exceptions or logs.
"""
from __future__ import annotations

import math
import threading
import time
from datetime import UTC, datetime

import httpx

from app.core.config import get_settings

SOURCE_URL = "https://www.eia.gov/electricity/data/browser/"
DATA_URL = "https://api.eia.gov/v2/electricity/retail-sales/data/"
SECTORS = {"RES": "Hogares", "COM": "Comercios y servicios", "IND": "Industria", "TRA": "Transporte", "OTH": "Otros"}
_cache: dict = {}
_lock = threading.RLock()


def parse_retail_revenue(rows: list[dict]) -> tuple[str, list[dict], float]:
    """Require one common complete year, US-only, exact monetary unit.

    ALL is a control total, never added to its component sectors. Duplicates,
    missing sectors, negative/non-finite values and unrecognized units fail
    closed. The provider may revise historical observations.
    """
    years = sorted({str(r.get("period", "")) for r in rows}, reverse=True)
    for year in years:
        if not (year.isdigit() and len(year) == 4 and int(year) < datetime.now(UTC).year):
            continue
        candidates = [r for r in rows if str(r.get("period")) == year and r.get("stateid") == "US"]
        by_sector = {}
        for row in candidates:
            code = row.get("sectorid")
            if code not in {*SECTORS, "ALL"}:
                continue
            if code in by_sector or row.get("revenue-units") != "million dollars":
                raise ValueError("EIA duplicate sector or unexpected revenue unit")
            value = float(row["revenue"])
            if not math.isfinite(value) or value < 0:
                raise ValueError("EIA invalid revenue")
            by_sector[code] = value * 1e6
        if set(by_sector) != {*SECTORS, "ALL"}:
            continue
        total = by_sector.pop("ALL")
        if not math.isclose(sum(by_sector.values()), total, rel_tol=1e-5, abs_tol=10):
            raise ValueError("EIA sector revenues do not reconcile")
        return year, [{"key": code, "label": SECTORS[code], "amount": amount} for code, amount in by_sector.items()], total
    raise ValueError("EIA no complete annual US revenue data")


def load_revenue() -> tuple[str, list[dict], float]:
    key = get_settings().eia_api_key
    if not key:
        raise RuntimeError("EIA not configured")
    now = time.monotonic()
    with _lock:
        if _cache.get("failed_until", 0) > now:
            raise RuntimeError("EIA temporarily unavailable")
        if _cache.get("until", 0) > now:
            return _cache["data"]
    try:
        response = httpx.get(DATA_URL, params={
            "api_key": key, "frequency": "annual", "data[0]": "revenue",
            "facets[stateid][]": "US", "sort[0][column]": "period",
            "sort[0][direction]": "desc", "length": 24,
        }, timeout=15)
        response.raise_for_status()
        parsed = parse_retail_revenue(response.json()["response"]["data"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError, OverflowError):
        with _lock:
            _cache["failed_until"] = now + 120
        raise RuntimeError("EIA temporarily unavailable") from None
    with _lock:
        _cache.update(data=parsed, until=now + 3600, failed_until=0)
    return parsed


def build_energy_flow(theme) -> dict:
    payload = {
        "id": theme.id, "name": theme.name, "tagline": theme.tagline,
        "generated_at": datetime.now(UTC), "period_label": None,
        "spenders": [], "spenders_total": None, "destinations": [], "suppliers": [],
        "method": theme.method, "limitation": theme.limitation,
        "notes": [], "destinations_note": None, "suppliers_note": None,
    }
    try:
        year, sectors, total = load_revenue()
    except RuntimeError:
        payload["notes"] = ["EIA no configurada o no disponible: gasto eléctrico N/D. No se estiman importes."]
        return payload
    source = {"kind": "reportado", "label": f"EIA · ventas eléctricas EE. UU. · {year}", "url": SOURCE_URL,
              "note": "Ingresos declarados por vendedores de electricidad; datos revisables"}
    payload["period_label"] = year
    payload["spenders"] = [{
        "key": row["key"], "label": row["label"], "ticker": None,
        "amount": row["amount"], "unit": "USD", "period_label": year,
        "source": source, "reason": "Gasto de los clientes en electricidad al por menor, medido por ingresos de ventas.",
        "note": None, "extra_amount": None, "extra_label": None, "extra_source": None,
    } for row in sectors]
    payload["spenders_total"] = {"amount": total, "unit": "USD", "note": f"5 de 5 sectores incluidos · EE. UU. {year}; ALL es control, no se suma otra vez"}
    payload["destinations"] = [{"label": "Compra de electricidad al por menor", "amount": total, "unit": "USD", "source": source}]
    payload["suppliers"] = [{"ticker": None, "name": "Vendedores de electricidad en EE. UU. (agregado)",
                             "amount": total, "unit": "USD", "source": source,
                             "reason": "Mismo ingreso que el gasto mostrado arriba; no es un flujo adicional.",
                             "note": "Sin reparto de estos ingresos entre empresas cotizadas"}]
    payload["suppliers_note"] = "Total agregado del mismo flujo, no ingresos atribuibles a las empresas de la cesta"
    return payload
