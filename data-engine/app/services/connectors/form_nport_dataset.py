"""Form N-PORT Data Sets de la SEC (DERA): carteras de fondos y ETF registrados.

Fuente oficial y gratuita: https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets
(un ZIP por trimestre de presentación). Solo se LEE y se agrega de forma
determinista; sin modelo. El cruce es por CUSIP exacto (lo pone quien llama).

Reglas:
- Posición = filas de FUND_REPORTED_HOLDING con ese CUSIP, largas
  (PAYOFF_PROFILE «Long»), en acciones (UNIT «NS»); se suman las filas del
  mismo informe. El peso es el PERCENTAGE que declara el fondo (% del
  patrimonio neto), sumado igual.
- Por serie (SERIES_ID) manda el informe con la REPORT_DATE más reciente; a
  igualdad, el presentado después (una NPORT-P/A sustituye al original).
- N-PORT público es trimestral (el último mes de cada trimestre fiscal del
  fondo) y se publica con hasta 60 días de retraso.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import IO

from app.services.connectors.form13f_dataset import SEC_BASE, _get, _rows

DATASETS_PAGE = "https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets"
_LINK = re.compile(r'href="(/files/[^"]*?/(\d{4})q([1-4])_nport\.zip)"', re.I)


@dataclass(frozen=True)
class NportDatasetRef:
    url: str
    year: int
    quarter: int

    @property
    def label(self) -> str:
        return f"{self.year}q{self.quarter}"


def list_datasets(html: str) -> list[NportDatasetRef]:
    seen = {path: NportDatasetRef(SEC_BASE + path, int(y), int(q)) for path, y, q in _LINK.findall(html)}
    return sorted(seen.values(), key=lambda r: (r.year, r.quarter), reverse=True)


def _date(raw: str) -> date | None:
    try:
        return datetime.strptime(raw.strip().upper(), "%d-%b-%Y").date()
    except ValueError:
        return None


def _dec(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.strip().replace(",", "")) if raw.strip() else None
    except InvalidOperation:
        return None


@dataclass
class FundReport:
    accession: str
    filed: date
    report_date: date
    form: str
    cik: str = ""
    registrant: str = ""
    series_id: str = ""
    series_name: str = ""
    net_assets: Decimal | None = None
    shares: dict[str, Decimal] = field(default_factory=dict)
    value: dict[str, Decimal | None] = field(default_factory=dict)
    weight: dict[str, Decimal | None] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """Nombre de la serie; si el fondo la deja vacía o en «N/A», el del registrante."""
        name = self.series_name.strip()
        return name if name and name.upper() not in {"N/A", "NA", "NONE", "-"} else self.registrant


def _add_component(totals: dict[str, Decimal | None], cusip: str, value: Decimal | None) -> None:
    """A missing component makes the whole reported aggregate unknown."""
    before = totals.get(cusip, Decimal(0))
    totals[cusip] = (
        before + value
        if before is not None and value is not None and value.is_finite()
        else None
    )


def parse_dataset(source: str | IO[bytes], cusips: set[str]) -> dict[str, FundReport]:
    """Informes N-PORT del ZIP con sus posiciones en ``cusips``, por accession."""
    wanted = {c.strip().upper() for c in cusips if c}
    reports: dict[str, FundReport] = {}
    with zipfile.ZipFile(source) as zf:
        for index, row in _rows(zf, "SUBMISSION.tsv"):
            acc = _get(index, row, "ACCESSION_NUMBER")
            form = _get(index, row, "SUB_TYPE").upper()
            filed, rep = _date(_get(index, row, "FILING_DATE")), _date(_get(index, row, "REPORT_DATE"))
            if acc and filed and rep and form in {"NPORT-P", "NPORT-P/A"}:
                reports[acc] = FundReport(acc, filed, rep, form)
        for index, row in _rows(zf, "REGISTRANT.tsv"):
            rep_ = reports.get(_get(index, row, "ACCESSION_NUMBER"))
            if rep_ is not None:
                rep_.cik = _get(index, row, "CIK").zfill(10)
                rep_.registrant = _get(index, row, "REGISTRANT_NAME")[:160]
        for index, row in _rows(zf, "FUND_REPORTED_INFO.tsv"):
            rep_ = reports.get(_get(index, row, "ACCESSION_NUMBER"))
            if rep_ is not None:
                rep_.series_id = _get(index, row, "SERIES_ID")
                rep_.series_name = _get(index, row, "SERIES_NAME")[:160]
                rep_.net_assets = _dec(_get(index, row, "NET_ASSETS"))
        if wanted:
            for index, row in _rows(zf, "FUND_REPORTED_HOLDING.tsv"):
                cusip = _get(index, row, "ISSUER_CUSIP").upper()
                if cusip not in wanted:
                    continue
                rep_ = reports.get(_get(index, row, "ACCESSION_NUMBER"))
                if rep_ is None or _get(index, row, "UNIT").upper() != "NS" or _get(index, row, "PAYOFF_PROFILE").lower() != "long":
                    continue
                shares = _dec(_get(index, row, "BALANCE"))
                if not shares or shares <= 0:
                    continue
                rep_.shares[cusip] = rep_.shares.get(cusip, Decimal(0)) + shares
                value = _dec(_get(index, row, "CURRENCY_VALUE"))
                if _get(index, row, "CURRENCY_CODE").upper() not in {"", "USD"}:
                    value = None
                _add_component(rep_.value, cusip, value)
                pct = _dec(_get(index, row, "PERCENTAGE"))
                _add_component(rep_.weight, cusip, pct)
    return reports


def latest_by_series(reports: dict[str, FundReport]) -> dict[str, FundReport]:
    """El informe vigente de cada serie (REPORT_DATE más reciente; luego el último presentado)."""
    out: dict[str, FundReport] = {}
    for rep in reports.values():
        key = rep.series_id or f"{rep.cik}:{rep.series_name}"
        cur = out.get(key)
        if cur is None or (rep.report_date, rep.filed, rep.accession) > (cur.report_date, cur.filed, cur.accession):
            out[key] = rep
    return out


def filing_index_url(cik: str, accession: str) -> str:
    return f"{SEC_BASE}/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{accession}-index.htm"
