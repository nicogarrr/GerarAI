"""Bound untrusted HTTP/XLSX input before allocating XML trees or replacing holdings."""
import io
import zipfile
from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, EtfHolding
from app.services import etf_holdings as eh
from tests.test_etf_holdings_jedi import DIRECT, REAL_ROWS, filler, make_xlsx


def workbook(limit):
    payload = make_xlsx('All Holdings  11/13/2026', REAL_ROWS + filler())
    if limit == 'MAX_XLSX_COMPRESSION_RATIO':
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(payload)) as src, zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as dst:
            for entry in src.infolist():
                dst.writestr(entry.filename, src.read(entry))
        payload = buf.getvalue()
    return payload


@pytest.mark.parametrize('limit,value', [
    ('MAX_XLSX_ENTRIES', 1),
    ('MAX_XLSX_MEMBER_BYTES', 100),
    ('MAX_XLSX_TOTAL_BYTES', 100),
    ('MAX_XLSX_COMPRESSION_RATIO', 1),
    ('MAX_XLSX_ROWS', 3),
    ('MAX_DOWNLOAD_BYTES', 100),
])
def test_workbook_resource_limits_reject_before_parse(limit, value, monkeypatch):
    monkeypatch.setattr(eh, limit, value, raising=False)
    with pytest.raises(ValueError, match='ETF resource limit'):
        eh.parse_vaneck(workbook(limit))


class Chunks(httpx.SyncByteStream):
    def __iter__(self):
        yield b'x' * 60
        yield b'y' * 60
        raise AssertionError('download must stop before consuming more chunks')


def test_stream_download_limit_aborts_without_content_length(monkeypatch):
    monkeypatch.setattr(eh, 'MAX_DOWNLOAD_BYTES', 100, raising=False)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Chunks()))) as client:
        with pytest.raises(ValueError, match='ETF resource limit'):
            eh._download_bytes(client, DIRECT)


def test_download_declared_size_rejected_before_body(monkeypatch):
    monkeypatch.setattr(eh, 'MAX_DOWNLOAD_BYTES', 100, raising=False)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={'content-length': '101'}, stream=Chunks()))) as client:
        with pytest.raises(ValueError, match='ETF resource limit'):
            eh._download_bytes(client, DIRECT)


@pytest.mark.parametrize('limit,value', [
    ('MAX_DOWNLOAD_BYTES', 100), ('MAX_XLSX_ENTRIES', 1),
    ('MAX_XLSX_MEMBER_BYTES', 100), ('MAX_XLSX_TOTAL_BYTES', 100),
    ('MAX_XLSX_COMPRESSION_RATIO', 1), ('MAX_XLSX_ROWS', 3),
])
def test_each_limit_keeps_previous_holdings(limit, value, monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info['tenant_id'] = 'tenant-test'
        db.add(EtfHolding(etf='JEDI', ticker='ASTS', weight_pct=Decimal('4.5'), as_of=date(2026, 11, 12), source_url='previous'))
        db.commit()
        monkeypatch.setattr(eh, limit, value, raising=False)
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=workbook(limit)))) as client:
            out = eh.refresh_etf_holdings(db, client)
        assert 'se conserva' in out['JEDI']
        row = db.scalar(select(EtfHolding).where(EtfHolding.etf == 'JEDI'))
        assert row.ticker == 'ASTS' and row.weight_pct == Decimal('4.5') and row.source_url == 'previous'


def rewrite_sheet(payload, transform):
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload)) as src, zipfile.ZipFile(buf, 'w') as dst:
        for entry in src.infolist():
            content = src.read(entry)
            if entry.filename == 'xl/worksheets/sheet1.xml':
                content = transform(content.decode()).encode()
            dst.writestr(entry.filename, content)
    return buf.getvalue()


def test_missing_leading_cells_keep_excel_column_positions():
    # Missing A4/B4 must not shift ticker C4, ISIN D4 and weight G4.
    import re
    data = make_xlsx('All Holdings  11/13/2026', [REAL_ROWS[0]])
    data = rewrite_sheet(data, lambda text: re.sub(r'<x:c r="[AB]4".*?</x:c>', '', text))
    _, rows = eh.parse_vaneck(data)
    assert rows == [('RKLB', Decimal('8.98'))]


def test_reordered_header_rejected_instead_of_guessing_positions():
    def swap(text):
        import re
        c = re.search(r'<x:c r="C3".*?</x:c>', text).group()
        d = re.search(r'<x:c r="D3".*?</x:c>', text).group()
        return text.replace(c, d.replace('D3', 'C3')).replace(d, c.replace('C3', 'D3'))
    data = rewrite_sheet(make_xlsx('All Holdings  11/13/2026', REAL_ROWS), swap)
    with pytest.raises(ValueError, match='ETF schema'):
        eh.parse_vaneck(data)


@pytest.mark.parametrize('isin', ['US1', 'US000000000X', 'US00000000000', 'US!000000000'])
def test_malformed_isin_rejected(isin):
    with pytest.raises(ValueError, match='ETF schema'):
        eh.parse_vaneck(make_xlsx('All Holdings  11/13/2026', [['1', 'Fixture', 'ASTS US', isin, '1', '$1', '2%']]))


@pytest.mark.parametrize('encoding,length', [('gzip', None), ('identity', 'not-a-number')])
def test_invalid_http_envelope_rejected(encoding, length):
    headers = {'content-encoding': encoding}
    if length:
        headers['content-length'] = length
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, headers=headers, stream=Chunks()))) as client:
        with pytest.raises(ValueError, match='ETF resource limit'):
            eh._download_bytes(client, DIRECT)


def test_duplicate_zip_members_rejected():
    data = make_xlsx('All Holdings  11/13/2026', REAL_ROWS)
    buf = io.BytesIO(data)
    with zipfile.ZipFile(buf, 'a') as zf, pytest.warns(UserWarning, match='Duplicate name'):
        zf.writestr('xl/sharedStrings.xml', '<sst/>')
    with pytest.raises(ValueError, match='ETF resource limit: duplicate'):
        eh.parse_vaneck(buf.getvalue())


@pytest.mark.parametrize('transform', [
    lambda s: s.replace('r="C4"', 'r="AA4"'),
    lambda s: s.replace('r="C4"', 'r="C5"'),
    lambda s: s.replace('r="C4"', 'r="H4"'),
    lambda s: s.replace('r="C4"', 'r="B4"'),
    lambda s: s.replace('<x:c r="C4" t="s"><x:v>', '<x:c r="C4" t="s"><x:v>999999'),
])
def test_invalid_cell_schema_rejected(transform):
    data = rewrite_sheet(make_xlsx('All Holdings  11/13/2026', REAL_ROWS), transform)
    with pytest.raises(ValueError, match='ETF schema'):
        eh.parse_vaneck(data)


def test_inline_strings_supported_without_shifting_columns():
    import re
    data = rewrite_sheet(make_xlsx('All Holdings  11/13/2026', [REAL_ROWS[0]]), lambda s: re.sub(
        r'<x:c r="C4".*?</x:c>', '<x:c r="C4" t="inlineStr"><x:is><x:t>RKLB US</x:t></x:is></x:c>', s))
    assert eh.parse_vaneck(data)[1] == [('RKLB', Decimal('8.98'))]


@pytest.mark.parametrize('change', ['reordered', 'missing_weight', 'missing_isin'])
def test_schema_change_keeps_previous_holdings(change):
    import re
    data = make_xlsx('All Holdings  11/13/2026', REAL_ROWS + filler())
    if change == 'reordered':
        data = rewrite_sheet(data, lambda s: s.replace('r="C3"', 'r="H3"'))
    else:
        col = 'G' if change == 'missing_weight' else 'D'
        data = rewrite_sheet(data, lambda s: re.sub(fr'<x:c r="{col}4".*?</x:c>', '', s))
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info['tenant_id'] = 'tenant-test'
        db.add(EtfHolding(etf='JEDI', ticker='ASTS', weight_pct=Decimal('4.5'), as_of=date(2026, 11, 12), source_url='previous'))
        db.commit()
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=data))) as client:
            assert 'se conserva' in eh.refresh_etf_holdings(db, client)['JEDI']
        row = db.scalar(select(EtfHolding).where(EtfHolding.etf == 'JEDI'))
        assert row.source_url == 'previous' and row.weight_pct == Decimal('4.5')


class UnreadRedirectBody(httpx.SyncByteStream):
    def __iter__(self):
        raise AssertionError('redirect body must never be buffered')
        yield b''


def test_redirect_body_not_drained_and_cookie_preserved():
    def handler(request):
        if 'country=uk' not in request.headers.get('cookie', ''):
            return httpx.Response(302, headers={'location': DIRECT + '?cken=true', 'set-cookie': 'country=uk; Path=/'}, stream=UnreadRedirectBody())
        return httpx.Response(200, content=b'ok')
    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        assert eh._download_bytes(client, DIRECT) == b'ok'


@pytest.mark.parametrize('location', [None, 'http://example.com/', DIRECT])
def test_bad_or_looping_redirect_rejected(location):
    headers = {'location': location} if location else {}
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(302, headers=headers, stream=UnreadRedirectBody()))) as client:
        with pytest.raises(ValueError, match='ETF (schema|resource limit)'):
            eh._download_bytes(client, DIRECT)
