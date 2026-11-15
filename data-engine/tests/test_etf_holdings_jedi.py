"""JEDI (VanEck Space Innovators UCITS): Excel oficial «All Holdings», solo EEUU."""

import io
import zipfile
from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, EtfHolding
from app.services import etf_holdings as eh

DIRECT = "https://www.vaneck.com/uk/en/investments/space-etf/downloads/holdings/"

# Filas copiadas del fichero real JEDI_asof_20261113.xlsx (descargado de VanEck el 15-nov-2026).
REAL_ROWS = [
    ["1", "Rocket Lab Corp", "RKLB US", "US7731211089", "2,171,711", "$ 139,141,524.00", "8.98%"],
    ["5", "Mda Space Ltd", "MDA US", "CA55293N1096", "3,268,543", "$ 95,310,714.00", "6.15%"],
    ["7", "Melrose Industries Plc", "MRO LN", "GB00BNGDN821", "11,802,981", "$ 76,464,780.00", "4.93%"],
    ["8", "Ast Spacemobile Inc", "ASTS US", "US00217D1000", "2,194,325", "$ 75,704,213.00", "4.89%"],
    ["12", "Sky Perfect Jsat Holdings Inc", "9412 JP", "JP3396350005", "5,564,300", "$ 61,454,370.00", "3.97%"],
    ["25", "Gilat Satellite Networks Ltd", "GILT US", "IL0010825102", "1,760,230", "$ 10,086,118.00", "0.65%"],
    ["26", "Other/Cash", " -- ", " -- ", " -- ", "$ 478,943.00", "0.03%"],
]
US_TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH", "III", "JJJ"]


def make_xlsx(header: str, rows: list[list[str]]) -> bytes:
    """xlsx minimo con el mismo esquema que VanEck (prefijo x:, cadenas compartidas)."""
    table = [[header] + [""] * 6, [""] * 7, ["Number", "Holding Name", "Ticker", "ISIN", "Shares", "Market Value", "% of Net Assets"], *rows]
    strings: list[str] = []
    sheet_rows = []
    for r, cells in enumerate(table, 1):
        out = []
        for c, val in enumerate(cells):
            if val not in strings:
                strings.append(val)
            out.append(f'<x:c r="{chr(65 + c)}{r}" t="s"><x:v>{strings.index(val)}</x:v></x:c>')
        sheet_rows.append(f'<x:row r="{r}">{"".join(out)}</x:row>')
    ns = 'xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    sst = "".join(f"<x:si><x:t>{escape(s)}</x:t></x:si>" for s in strings)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/sharedStrings.xml", f'<?xml version="1.0"?><x:sst {ns}>{sst}</x:sst>')
        zf.writestr("xl/worksheets/sheet1.xml", f'<?xml version="1.0"?><x:worksheet {ns}><x:sheetData>{"".join(sheet_rows)}</x:sheetData></x:worksheet>')
    return buf.getvalue()


def filler() -> list[list[str]]:
    return [[str(i), f"N{t}", f"{t} US", f"US000000000{i}", "1", "$ 1.00", "1.00%"] for i, t in enumerate(US_TICKERS)]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def test_parse_vaneck_keeps_us_listed_with_us_isin_and_header_date():
    as_of, rows = eh.parse_vaneck(make_xlsx("All Holdings  11/13/2026", REAL_ROWS))
    assert as_of == date(2026, 11, 13)
    assert dict(rows) == {"RKLB": Decimal("8.98"), "ASTS": Decimal("4.89")}
    # MDA (ISIN canadiense), GILT (ISIN israeli), MRO LN, 9412 JP y Other/Cash fuera.


def test_parse_vaneck_rejects_missing_or_bad_date_and_bad_weight():
    with pytest.raises(ValueError, match="invalid equity date"):
        eh.parse_vaneck(make_xlsx("Holdings sin fecha", REAL_ROWS))
    with pytest.raises(ValueError, match="invalid equity date"):
        eh.parse_vaneck(make_xlsx("All Holdings  13/13/2026", REAL_ROWS))
    with pytest.raises(ValueError, match="invalid equity weight"):
        eh.parse_vaneck(make_xlsx("All Holdings  11/13/2026", [["1", "X", "XYZ US", "US0000000000", "1", "$ 1", "n/d"]]))


def _cookie_client(payload: bytes, status: int = 200):
    """Imita VanEck: la 1.a peticion sin cookie redirige a ?cken=true y fija la cookie."""
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).split("?")[0] != DIRECT:
            return httpx.Response(404)
        if "ve-country-uk" not in request.headers.get("cookie", ""):
            return httpx.Response(302, headers={"location": DIRECT + "?cken=true", "set-cookie": "ve-country-uk=iso%3Duk; Path=/"})
        return httpx.Response(status, content=payload)

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_refresh_stores_jedi_with_source_url_and_asts_links_to_etf(db):
    xlsx = make_xlsx("All Holdings  11/13/2026", REAL_ROWS + filler())
    out = eh.refresh_etf_holdings(db, _cookie_client(xlsx))
    assert out["JEDI"] == "ok 12 holdings as_of 2026-11-13"
    row = db.scalar(select(EtfHolding).where(EtfHolding.etf == "JEDI", EtfHolding.ticker == "ASTS"))
    assert row.weight_pct == Decimal("4.89") and row.as_of == date(2026, 11, 13) and row.source_url == DIRECT
    chips = eh.etfs_for_tickers(db, {"ASTS", "RKLB"}, today=date(2026, 11, 15))
    assert chips["ASTS"] == [{
        "ticker": "JEDI", "name": "VanEck Space Innovators UCITS ETF", "kind": "etf",
        "weight_pct": 4.89, "holdings_as_of": "2026-11-13", "source_url": DIRECT,
    }]


def test_refresh_keeps_previous_when_vaneck_fails_or_file_is_stale(db):
    eh.refresh_etf_holdings(db, _cookie_client(make_xlsx("All Holdings  11/13/2026", REAL_ROWS + filler())))
    out = eh.refresh_etf_holdings(db, _cookie_client(b"<html>bloqueado</html>"))
    assert "se conserva la carga anterior" in out["JEDI"]
    old = make_xlsx("All Holdings  11/06/2026", REAL_ROWS + filler())
    assert "anterior al guardado" in eh.refresh_etf_holdings(db, _cookie_client(old))["JEDI"]
    assert db.scalar(select(EtfHolding.as_of).where(EtfHolding.etf == "JEDI", EtfHolding.ticker == "ASTS")) == date(2026, 11, 13)
    assert "se conserva la carga anterior" in eh.refresh_etf_holdings(db, _cookie_client(b"", 403))["JEDI"]


def test_etfs_for_tickers_ignores_stale_jedi_and_light_weights(db):
    eh.refresh_etf_holdings(db, _cookie_client(make_xlsx("All Holdings  11/13/2026", REAL_ROWS + filler())))
    assert eh.etfs_for_tickers(db, {"ASTS"}, today=date(2027, 1, 20)) == {}  # >45 dias
    assert eh.etfs_for_tickers(db, {"AAA"}, today=date(2026, 11, 15)) == {}  # 1 % < 2 %
