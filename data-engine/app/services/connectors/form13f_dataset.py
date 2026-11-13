"""Form 13F Data Sets de la SEC (DERA): todas las carteras 13F de un periodo.

Fuente oficial y gratuita: https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets
(un ZIP por ventana de presentación de ~3 meses con SUBMISSION, COVERPAGE e
INFOTABLE en TSV). Aquí solo se LEE y se agrega de forma determinista; sin
modelo, sin inferir tickers (el cruce es por CUSIP exacto, que pone quien
llama).

Reglas (las de la propia SEC para el formulario 13F):
- Una posición = filas de INFOTABLE con ese CUSIP, SIN opciones (PUTCALL
  vacío) y en acciones (SSHPRNAMTTYPE = SH); se suman las filas del mismo
  13F (un gestor puede repartirla por discreción o por otros gestores).
- Por gestor (CIK) y periodo manda el último 13F-HR original; una enmienda
  posterior «RESTATEMENT» lo sustituye entero y una «NEW HOLDINGS» suma sus
  filas. Una enmienda sin tipo no se aplica (se cuenta como ignorada).
- 13F-NT no trae posiciones (otro gestor las declara por él).
- Un 13F-HR original cuya INFOTABLE trae menos de la mitad de las filas que él
  mismo declara en SUMMARYPAGE (o ninguna) no es una cartera: la tabla vino
  aparte o mal fechada (visto en un 13F de 1.507 filas declaradas y 1 cargada,
  con la tabla en una enmienda fechada un año antes). Para ese periodo el
  gestor queda «sin 13F», nunca como «no tenía nada», salvo que una RESTATEMENT
  completa del mismo periodo traiga la cartera entera (visto en un banco: 378
  de 33.063 filas en el original y la tabla completa en su RESTATEMENT del
  mismo día). Una RESTATEMENT incompleta no sustituye nada.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import IO

DATASETS_PAGE = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
SEC_BASE = "https://www.sec.gov"
_LINK = re.compile(r'href="(/files/[^"]*?/(\d{2}[a-z]{3}\d{4})-(\d{2}[a-z]{3}\d{4})_form13f\.zip)"', re.I)

@dataclass(frozen=True)
class DatasetRef:
    url: str
    window_start: date
    window_end: date


def _ddmonyyyy(raw: str) -> date | None:
    try:
        return datetime.strptime(raw.strip().title(), "%d%b%Y").date()
    except ValueError:
        return None


def _sec_date(raw: str) -> date | None:
    try:
        return datetime.strptime(raw.strip().upper(), "%d-%b-%Y").date()
    except ValueError:
        return None


def list_datasets(html: str) -> list[DatasetRef]:
    """Enlaces a los ZIP de la página de la SEC, el más reciente primero."""
    seen: dict[str, DatasetRef] = {}
    for path, start, end in _LINK.findall(html):
        d0, d1 = _ddmonyyyy(start), _ddmonyyyy(end)
        if d0 and d1:
            seen[path] = DatasetRef(SEC_BASE + path, d0, d1)
    return sorted(seen.values(), key=lambda r: (r.window_end, r.url), reverse=True)


@dataclass
class Filing:
    accession: str
    cik: str
    filed: date
    period: date
    form: str
    manager: str = ""
    amendment_type: str = ""
    # cusip -> acciones (solo los CUSIP pedidos)
    shares: dict[str, Decimal] = field(default_factory=dict)
    # filas de INFOTABLE de este 13F (todas, no solo los CUSIP pedidos)
    table_rows: int = 0
    # filas que el propio 13F declara en su SUMMARYPAGE (TABLEENTRYTOTAL)
    declared_rows: int | None = None

    @property
    def complete(self) -> bool:
        """La tabla trae al menos la mitad de las filas que el 13F declara."""
        if self.table_rows == 0:
            return False
        return self.declared_rows is None or self.table_rows * 2 >= self.declared_rows


@dataclass
class DatasetParse:
    url: str
    filings: dict[str, Filing]


def _rows(zf: zipfile.ZipFile, name: str):
    """Filas de un TSV del ZIP (sin comillas: QUOTE_NONE de la SEC).

    Se parte a mano en vez de usar ``csv``: el módulo csv tiene un límite de
    campo GLOBAL al proceso y subirlo aquí cambiaría el de cualquier otro
    lector (importadores de CSV del usuario incluidos)."""
    with zf.open(name) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
        header = text.readline().rstrip("\r\n")
        if not header:
            return
        index = {h.strip().upper(): i for i, h in enumerate(header.split("\t"))}
        for line in text:
            line = line.rstrip("\r\n")
            if line:
                yield index, line.split("\t")


def _get(index: dict[str, int], row: list[str], key: str) -> str:
    i = index.get(key)
    return row[i].strip() if i is not None and i < len(row) else ""


def parse_dataset(source: str | IO[bytes], cusips: set[str], *, url: str = "") -> DatasetParse:
    """Lee un ZIP de 13F y devuelve cada 13F con las acciones de ``cusips``."""
    wanted = {c.strip().upper() for c in cusips if c}
    filings: dict[str, Filing] = {}
    with zipfile.ZipFile(source) as zf:
        for index, row in _rows(zf, "SUBMISSION.tsv"):
            acc = _get(index, row, "ACCESSION_NUMBER")
            form = _get(index, row, "SUBMISSIONTYPE").upper()
            filed = _sec_date(_get(index, row, "FILING_DATE"))
            period = _sec_date(_get(index, row, "PERIODOFREPORT"))
            if not acc or not filed or not period or form not in {"13F-HR", "13F-HR/A"}:
                continue
            if period > filed or filed > date.today():
                continue
            filings[acc] = Filing(acc, _get(index, row, "CIK").zfill(10), filed, period, form)
        for index, row in _rows(zf, "COVERPAGE.tsv"):
            filing = filings.get(_get(index, row, "ACCESSION_NUMBER"))
            if filing is None:
                continue
            filing.manager = _get(index, row, "FILINGMANAGER_NAME")[:160]
            filing.amendment_type = _get(index, row, "AMENDMENTTYPE").upper()
        if "SUMMARYPAGE.tsv" in zf.namelist():
            for index, row in _rows(zf, "SUMMARYPAGE.tsv"):
                filing = filings.get(_get(index, row, "ACCESSION_NUMBER"))
                total = _get(index, row, "TABLEENTRYTOTAL")
                if filing is not None and total.isdigit():
                    filing.declared_rows = int(total)
        for index, row in _rows(zf, "INFOTABLE.tsv"):
            filing = filings.get(_get(index, row, "ACCESSION_NUMBER"))
            if filing is None:
                continue
            filing.table_rows += 1
            cusip = _get(index, row, "CUSIP").upper()
            if cusip not in wanted:
                continue
            if _get(index, row, "PUTCALL") or _get(index, row, "SSHPRNAMTTYPE").upper() != "SH":
                continue
            try:
                amount = Decimal(_get(index, row, "SSHPRNAMT").replace(",", ""))
            except ArithmeticError:
                continue
            # No se puede descartar esta posición y afirmar que el gestor
            # vendió todo. El job conserva el snapshot previo al fallar.
            if not amount.is_finite():
                raise ValueError("Cantidad 13F no finita: cartera no verificable")
            if amount < 0:
                raise ValueError("Cantidad 13F negativa: cartera no verificable")
            if amount > 0:
                filing.shares[cusip] = filing.shares.get(cusip, Decimal(0)) + amount
    return DatasetParse(url, filings)


@dataclass
class ManagerPeriod:
    """Lo declarado por un gestor en un periodo, tras aplicar enmiendas."""

    cik: str
    manager: str
    accession: str
    filed: date
    shares: dict[str, Decimal]
    amendments: list[str] = field(default_factory=list)
    url: str = ""


def resolve_periods(parses: list[DatasetParse]) -> tuple[dict[date, dict[str, ManagerPeriod]], int]:
    """Por periodo y CIK, la cartera vigente según las reglas del módulo.

    Devuelve (periodos, enmiendas_ignoradas + 13F originales sin filas)."""
    by_key: dict[tuple[str, date], list[tuple[Filing, str]]] = defaultdict(list)
    for parse in parses:
        for filing in parse.filings.values():
            by_key[(filing.cik, filing.period)].append((filing, parse.url))
    out: dict[date, dict[str, ManagerPeriod]] = defaultdict(dict)
    ignored = 0
    empty = 0
    for (cik, period), items in by_key.items():
        items.sort(key=lambda x: (x[0].filed, x[0].accession))
        originals = [it for it in items if it[0].form == "13F-HR" and it[0].complete]
        if not originals:
            # Original incompleto, pero con una RESTATEMENT completa: esa es la cartera.
            originals = [it for it in items if it[0].form == "13F-HR/A" and it[0].amendment_type.startswith("RESTATEMENT")
                         and it[0].complete]
        if not originals:
            empty += sum(1 for it in items if it[0].form == "13F-HR")
            continue
        base, url = originals[-1]
        current = ManagerPeriod(cik, base.manager, base.accession, base.filed, dict(base.shares), url=url)
        for filing, _ in items:
            if filing.form != "13F-HR/A" or (filing.filed, filing.accession) <= (base.filed, base.accession):
                continue
            if filing.amendment_type.startswith("RESTATEMENT"):
                if not filing.complete:
                    ignored += 1
                    continue
                current = ManagerPeriod(cik, filing.manager or current.manager, filing.accession, filing.filed,
                                        dict(filing.shares), [*current.amendments, filing.accession], url=current.url)
            elif filing.amendment_type.startswith("NEW HOLDINGS"):
                for cusip, amount in filing.shares.items():
                    current.shares[cusip] = current.shares.get(cusip, Decimal(0)) + amount
                current.amendments.append(filing.accession)
            else:
                ignored += 1
        out[period][cik] = current
    return dict(out), ignored + empty


def filing_index_url(cik: str, accession: str) -> str:
    """Índice EDGAR del 13F concreto (para citar cada cifra)."""
    return f"{SEC_BASE}/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{accession}-index.htm"
