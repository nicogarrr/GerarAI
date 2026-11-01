"""Only current public CNMV notices, with reviewed issuer identity."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
from lxml import html

from app.services.cnmv_mapping import CNMVIssuer
from app.services.data_source_health import get_data_source_registry

# Misma fuente que connectors/cnmv.py (www.cnmv.es): comparten clave "cnmv".
# Los ValueError del parser son deriva de estructura o identidad no cuadrada:
# eso es exactamente la senal "la fuente cambio" y SI degrada.
_REGISTRY_KEY = "cnmv"

CNMV_SHORTS_URL = "https://www.cnmv.es/portal/consultas/ee/posicionescortas"


def parse_positions(page: str, issuer: CNMVIssuer, *, now: datetime | None = None) -> list[dict]:
    tree = html.fromstring(page)
    # Both identity and the current-notice caption must be present. An empty
    # page or historical table never means zero short positions.
    if issuer.isin not in tree.text_content():
        raise ValueError("CNMV issuer identity mismatch")
    tables = tree.xpath('//table[caption[contains(., "Notificaciones vivas iguales o superiores")]]')
    if len(tables) != 1:
        raise ValueError("CNMV current table unavailable")
    rows = []
    holders = set()
    for row in tables[0].xpath(".//tbody/tr"):
        cells = [cell.text_content().strip() for cell in row.xpath("./td")]
        if len(cells) != 4 or not cells[0]:
            raise ValueError("CNMV table drift")
        percent = Decimal(cells[1].replace(".", "").replace(",", "."))
        stamp = datetime.strptime(cells[2], "%d/%m/%Y").date()
        if not percent.is_finite() or not Decimal("0.5") <= percent <= 100 or cells[0] in holders:
            raise ValueError("Invalid public position")
        if stamp > (now or datetime.now(UTC)).date():
            raise ValueError("Future position date")
        holders.add(cells[0])
        rows.append({"holder": cells[0], "percent": float(percent), "position_date": stamp.isoformat()})
    return rows


async def fetch_positions(issuer: CNMVIssuer, *, client: httpx.AsyncClient | None = None) -> dict:
    nif = issuer.nif.replace("-", "")
    params = {"lang": "es", "nif": nif}
    if client is None:
        async with httpx.AsyncClient(timeout=12, follow_redirects=False) as owned:
            return await fetch_positions(issuer, client=owned)
    registry = get_data_source_registry()
    try:
        response = await client.get(CNMV_SHORTS_URL, params=params)
        response.raise_for_status()
        rows = parse_positions(response.text, issuer)
    except httpx.HTTPStatusError as exc:
        registry.record_failure(_REGISTRY_KEY, f"HTTP {exc.response.status_code}")
        raise
    except httpx.TransportError as exc:
        registry.record_failure(_REGISTRY_KEY, f"error de red: {type(exc).__name__}")
        raise
    except ValueError as exc:
        registry.record_failure(_REGISTRY_KEY, f"parseo: {exc}")
        raise
    registry.record_success(_REGISTRY_KEY)
    return {
        "positions": rows,
        "public_total_percent": float(sum(Decimal(str(row["percent"])) for row in rows)),
        "source": "CNMV",
        "source_url": str(response.url),
        "kind": "OFICIAL",
        "total_kind": "DERIVADO",
        "threshold_percent": 0.5,
        "note": "Solo posiciones públicas >=0,5%. La suma no es el total de cortos del mercado; fechas distintas por titular.",
    }
