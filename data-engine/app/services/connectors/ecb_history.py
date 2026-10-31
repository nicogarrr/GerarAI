"""Tipos de cambio históricos oficiales del BCE para el informe fiscal.

El IRPF convierte cada operación en divisa al tipo de SU fecha: la compra al
de la fecha de compra y la venta al de la fecha de venta (art. 34-35 LIRPF;
Manual Renta 2025, cap. 11). El refresco diario de mercado solo guarda el
tipo del día en que corre, así que las fechas de operaciones antiguas (o los
días sin refresco) quedaban sin tipo o con uno de semanas antes.

Este módulo descarga la serie diaria de referencia del BCE (la misma que
publica el Banco de España como «cambios oficiales del euro») para un rango
de fechas y la guarda en ``fx_rates`` con ``source="ECB"``:

- Fuente: ECB Data Portal, dataset EXR, serie ``D.<DIVISA>.EUR.SP00.A``
  (https://data-api.ecb.europa.eu/service/data/EXR/...). El BCE publica
  unidades de divisa por 1 EUR; aquí se guarda la convención de la tabla:
  importe en divisa × rate = importe en EUR, es decir rate = 1 / publicado.
- Subunidades: GBX/GBp (peniques) = GBP / 100, ZAC = ZAR / 100, ILA = ILS /
  100. El BCE no publica subunidades; se derivan de la divisa principal.
- Nunca se inventa un tipo: un día sin publicación (fin de semana, festivo
  TARGET) no se rellena; el informe usa el último publicado y descarta los
  de más de ``MAX_FX_AGE_DAYS`` días (ver ``tax_report_service``).
"""

from __future__ import annotations

import csv
import io
import time
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy.orm import Session

from app.services.data_source_health import get_data_source_registry
from app.services.portfolio_fx_service import PortfolioFXService

# Misma fuente que connectors/ecb.py (data-api.ecb.europa.eu): comparten clave "ecb" en
# el registry para que el circuito agregue todos los outcomes del proveedor.
_ECB_REGISTRY_KEY = "ecb"
from app.valuation.currency import normalize_currency

ECB_DATA_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{codes}.EUR.SP00.A"
ECB_SOURCE = "ECB"

#: Subunidad → (divisa principal, divisor).
MINOR_UNITS: dict[str, tuple[str, Decimal]] = {
    "GBX": ("GBP", Decimal("100")),
    "ZAC": ("ZAR", Decimal("100")),
    "ILA": ("ILS", Decimal("100")),
}


def _normalize(code: str) -> str:
    """Codigo de subunidad canonico para el BCE, con la MISMA tabla que la
    valoracion (``normalize_currency``): GBp/GBX/GBPENCE -> GBX, ZAc -> ZAC,
    ILa/ILX -> ILA. Antes solo ``GBp`` se reconocia aqui; cualquier otra
    grafia de subunidad que el resto del codigo ya divide entre 100 se pedia
    al BCE como si fuese una divisa (que no existe) y el informe fiscal se
    quedaba sin tipo para esas operaciones."""
    normalized = code.strip()
    major, divisor = normalize_currency(normalized)
    if major is not None and divisor != 1:
        for minor, (minor_major, minor_divisor) in MINOR_UNITS.items():
            if minor_major == major and minor_divisor == divisor:
                return minor
    return normalized.upper()


def parse_ecb_csv(text: str) -> list[tuple[date, str, Decimal]]:
    """Parsea el CSV ``format=csvdata`` del BCE → [(fecha, divisa, unidades por EUR)]."""
    out: list[tuple[date, str, Decimal]] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        currency = (row.get("CURRENCY") or "").strip().upper()
        raw_date = (row.get("TIME_PERIOD") or "").strip()
        raw_value = (row.get("OBS_VALUE") or "").strip()
        if not currency or not raw_date or not raw_value:
            continue
        try:
            value = Decimal(raw_value)
            day = date.fromisoformat(raw_date)
        except (InvalidOperation, ValueError):
            continue
        if value <= 0:
            continue
        out.append((day, currency, value))
    return out


async def fetch_ecb_csv(codes: list[str], start: date, end: date) -> str:
    """Descarga la serie diaria del BCE (una petición para todas las divisas)."""
    url = ECB_DATA_URL.format(codes="+".join(sorted(codes)))
    registry = get_data_source_registry()
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(
                url,
                params={
                    "startPeriod": start.isoformat(),
                    "endPeriod": end.isoformat(),
                    "format": "csvdata",
                },
            )
            response.raise_for_status()
            text = response.text
    except httpx.HTTPStatusError as exc:
        # URL fija por divisas conocidas: un error HTTP es de la fuente.
        registry.record_failure(_ECB_REGISTRY_KEY, f"HTTP {exc.response.status_code}")
        raise
    except httpx.TransportError as exc:
        registry.record_failure(_ECB_REGISTRY_KEY, f"error de red: {type(exc).__name__}")
        raise
    registry.record_success(_ECB_REGISTRY_KEY, (time.perf_counter() - started) * 1000)
    return text


async def backfill_ecb_rates(
    db: Session,
    *,
    currencies: set[str],
    start: date,
    end: date,
    base_currency: str = "EUR",
    fetcher: Callable[[list[str], date, date], Awaitable[str]] = fetch_ecb_csv,
) -> dict:
    """Guarda los tipos BCE de ``start`` a ``end`` para ``currencies`` en ``fx_rates``.

    Devuelve un resumen con las filas escritas por divisa y las divisas que
    el BCE no publica. Solo base EUR: el informe fiscal es en euros y una
    base distinta no tiene tipo oficial directo.
    """
    base = base_currency.strip().upper()
    if base != "EUR":
        raise ValueError("Los tipos oficiales del BCE se guardan solo con base EUR")
    wanted = {_normalize(c) for c in currencies if c and _normalize(c) != "EUR"}
    major_for: dict[str, list[tuple[str, Decimal]]] = {}
    for code in wanted:
        major, divisor = MINOR_UNITS.get(code, (code, Decimal("1")))
        major_for.setdefault(major, []).append((code, divisor))
    summary: dict = {"source": ECB_SOURCE, "written": {}, "not_published": []}
    if not major_for:
        return summary
    observations = parse_ecb_csv(await fetcher(sorted(major_for), start, end))
    fx = PortfolioFXService()
    published: set[str] = set()
    for day, major, units_per_eur in observations:
        if major not in major_for:
            continue
        published.add(major)
        # Se guarda SIEMPRE la fila de la divisa principal (1 major =
        # 1/units_per_eur EUR): todos los lectores (``PortfolioFXService.rate``,
        # ``fx_table``) normalizan la subunidad (GBp/GBX -> GBP / 100) y buscan
        # la fila de GBP. Antes se guardaba una fila ``GBX`` con el tipo ya
        # dividido entre 100 que nadie lee: una cartera solo con valores en
        # peniques seguia sin tipo tras la descarga (coste en EUR y dividendos
        # del informe fiscal «sin tipo»).
        fx.upsert_rate(
            db,
            base_currency=base,
            quote_currency=major,
            rate=Decimal("1") / units_per_eur,
            rate_date=day,
            source=ECB_SOURCE,
        )
        for code, _divisor in major_for[major]:
            summary["written"][code] = summary["written"].get(code, 0) + 1
    db.commit()
    summary["not_published"] = sorted(
        code for major, codes in major_for.items() if major not in published for code, _ in codes
    )
    return summary


def fetch_ecb_csv_sync(codes: list[str], start: date, end: date) -> str:
    """Igual que :func:`fetch_ecb_csv` pero sincrono (lo usa el ledger, que es sync)."""
    url = ECB_DATA_URL.format(codes="+".join(sorted(codes)))
    registry = get_data_source_registry()
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(
                url,
                params={
                    "startPeriod": start.isoformat(),
                    "endPeriod": end.isoformat(),
                    "format": "csvdata",
                },
            )
            response.raise_for_status()
            text = response.text
    except httpx.HTTPStatusError as exc:
        registry.record_failure(_ECB_REGISTRY_KEY, f"HTTP {exc.response.status_code}")
        raise
    except httpx.TransportError as exc:
        registry.record_failure(_ECB_REGISTRY_KEY, f"error de red: {type(exc).__name__}")
        raise
    registry.record_success(_ECB_REGISTRY_KEY, (time.perf_counter() - started) * 1000)
    return text


def backfill_ecb_rates_sync(
    db: Session,
    *,
    currencies: set[str],
    start: date,
    end: date,
    fetcher: Callable[[list[str], date, date], str] = fetch_ecb_csv_sync,
) -> dict:
    """Version sincrona de :func:`backfill_ecb_rates` (misma escritura en ``fx_rates``)."""

    async def _adapter(codes: list[str], s: date, e: date) -> str:
        return fetcher(codes, s, e)

    from app.services.async_bridge import run_from_any_context

    return run_from_any_context(
        backfill_ecb_rates(db, currencies=currencies, start=start, end=end, fetcher=_adapter)
    )
