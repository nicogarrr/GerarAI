"""Documento financiero oficial DISTINTO de la transcripcion: comunicado de resultados (SEC).

- Registro exacto aparte (URL SEC + periodo + fecha); NO es transcript ni amplia ningun CDN.
- Extrae solo la FILA "Gross Bookings" de la tabla con cabeceras de columna verificadas
  (crecimiento reportado vs moneda constante) y devuelve hechos SEPARADOS y etiquetados.
- Procedencia: el comunicado es del propio emisor. Es "resultado reportado por el emisor", NO
  evidencia independiente; contrastarlo con la transcripcion (mismo emisor) no verifica la
  afirmacion de la empresa. 22% (moneda constante) NUNCA se emite como reportado sin ajuste.
- Puro: no hace red ni escribe; el fetch del HTML lo hace quien llama con politica exacta.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser

ISSUER_REPORTED = "emisor_reportado"  # no es evidencia externa independiente


@dataclass(frozen=True)
class FinancialAsset:
    ticker: str
    url: str
    kind: str  # press_release
    period: str  # Q2 2026
    period_end: date
    published_on: date
    title_marker: str


FINANCIAL_ASSETS: tuple[FinancialAsset, ...] = (
    FinancialAsset(
        ticker="UBER",
        url="https://www.sec.gov/Archives/edgar/data/1543151/000154315126000027/uberq226earningspressrelea.htm",
        kind="press_release",
        period="Q2 2026",
        period_end=date(2026, 6, 30),
        published_on=date(2026, 8, 5),
        title_marker="Uber Announces Results for Second Quarter 2026",
    ),
)


def get_financial_asset(ticker: str, url: str) -> FinancialAsset | None:
    for asset in FINANCIAL_ASSETS:
        if asset.ticker == ticker.upper() and asset.url == url:
            return asset
    return None


@dataclass(frozen=True)
class ReleaseFact:
    metric: str  # gross_bookings_usd_m | gross_bookings_growth_yoy_reported | ..._constant_currency
    value: Decimal
    unit: str  # USD_m | %
    period: str
    period_end: date
    is_reported: bool
    is_adjusted: bool  # moneda constante = medida ajustada
    provenance: str  # ISSUER_REPORTED
    source_url: str
    source_kind: str
    row_text: str
    html_sha256: str


class _Rows(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            text = " ".join("".join(self._cell).replace("\xa0", " ").split())
            if text:
                self._row.append(text)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


_NUM = re.compile(r"-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?")


def extract_gross_bookings(
    *, asset: FinancialAsset, html: bytes, today: date,
) -> tuple[list[ReleaseFact], str]:
    """Devuelve (hechos, motivo). Abstiene (lista vacia) ante cualquier ambiguedad."""
    if asset.kind != "press_release" or asset.published_on > today:
        return [], "activo_no_valido"
    if len(html) > 4_000_000:
        return [], "documento_demasiado_grande"
    text = html.decode("utf-8", "ignore")
    if asset.title_marker not in " ".join(re.sub(r"<[^>]+>", " ", text[:20000]).split()):
        return [], "titulo_no_coincide"
    parser = _Rows()
    parser.feed(text)
    header_ok = False
    found: list[list[str]] = []
    for row in parser.rows:
        joined = " ".join(row).lower()
        if ("% change" in joined and "constant currency" in joined
                and "2025" in row and "2026" in row and row.index("2025") < row.index("2026")):
            header_ok = True
        if row and row[0] == "Gross Bookings" and header_ok:
            found.append(row)
    if len(found) != 1:
        return [], "fila_gross_bookings_no_unica_o_sin_cabecera"
    row = found[0]
    if row.count("%") != 2 or row.count("$") != 2:
        return [], "columnas_inesperadas"
    cells = [c for c in row[1:] if c not in {"$", "%"}]
    if len(cells) != 4 or not all(_NUM.fullmatch(c.replace(",", "")) for c in cells):
        return [], "valores_no_numericos"
    cur = cells[1].replace(",", "")
    pct = cells[2:]
    digest = hashlib.sha256(html).hexdigest()
    base = dict(
        period=asset.period, period_end=asset.period_end, provenance=ISSUER_REPORTED,
        source_url=asset.url, source_kind=asset.kind, row_text=" | ".join(row), html_sha256=digest,
    )
    return [
        ReleaseFact("gross_bookings_usd_m", Decimal(cur), "USD_m", is_reported=True, is_adjusted=False, **base),
        ReleaseFact("gross_bookings_growth_yoy_reported", Decimal(pct[0]), "%", is_reported=True, is_adjusted=False, **base),
        ReleaseFact("gross_bookings_growth_yoy_constant_currency", Decimal(pct[1]), "%", is_reported=True, is_adjusted=True, **base),
    ], "ok"
