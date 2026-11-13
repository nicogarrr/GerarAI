"""house_ptr: red doblada (indice anual zip, PDF), fechas ISO, importes y
contadores de parseo. Todo sintetico: zip/XML/PDF construidos en memoria,
cliente httpx falso, reloj doblado para _throttle (nunca tiempo real).

No se prueba aqui: pypdf real (pdf_text), ingest en base de datos (cubierto
en test_house_ptr.py) ni el scheduler. El PDF sintetico son bytes opacos:
lo que se verifica es la URL y el pase de bytes, no el contenido.
"""

import io
import zipfile

import pytest

from app.services.connectors import house_ptr as hp


@pytest.fixture(autouse=True)
def _reloj_doblado(monkeypatch):
    """_throttle nunca duerme de verdad ni filtra _last_request entre tests.

    Los dos tests especificos de _throttle traen su propio reloj: su
    monkeypatch.setattr posterior pisa al de este fixture.
    """
    monkeypatch.setattr(hp.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(hp.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(hp, "_last_request", 0.0)


def test_throttle_espera_lo_justo(monkeypatch):
    sleeps = []
    monkeypatch.setattr(hp.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(hp.time, "sleep", sleeps.append)
    monkeypatch.setattr(hp, "_last_request", 99.8)
    hp._throttle()
    assert sleeps == [pytest.approx(0.3)]
    assert hp._last_request == 100.0


def test_throttle_no_duerme_si_ya_paso_el_intervalo(monkeypatch):
    sleeps = []
    monkeypatch.setattr(hp.time, "monotonic", lambda: 101.0)
    monkeypatch.setattr(hp.time, "sleep", sleeps.append)
    monkeypatch.setattr(hp, "_last_request", 100.0)
    hp._throttle()
    assert sleeps == []
    assert hp._last_request == 101.0


class _Resp:
    def __init__(self, content=b"DATA"):
        self.content = content
        self.raised = False

    def raise_for_status(self):
        self.raised = True


class _FakeClient:
    def __init__(self, content=b"DATA"):
        self._resp = _Resp(content)
        self.calls = []

    def get(self, url, headers=None):
        self.calls.append((url, headers))
        return self._resp


def test_get_con_cliente_usa_headers_y_devuelve_contenido():
    client = _FakeClient()
    assert hp._get("https://example.test/x", client) == b"DATA"
    url, headers = client.calls[0]
    assert url == "https://example.test/x"
    assert headers == hp._headers()
    assert headers["User-Agent"]
    assert client._resp.raised is True


def test_get_sin_cliente_crea_uno_propio(monkeypatch):
    creado = {}

    class OwnedClient(_FakeClient):
        def __init__(self, **kwargs):
            super().__init__()
            creado["kwargs"] = kwargs
            creado["closed"] = False

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            creado["closed"] = True
            return False

    monkeypatch.setattr(hp.httpx, "Client", OwnedClient)
    assert hp._get("https://example.test/y") == b"DATA"
    assert creado["kwargs"]["timeout"] == 60
    assert creado["kwargs"]["follow_redirects"] is False
    assert creado["kwargs"]["headers"] == hp._headers()
    assert creado["closed"] is True


def test_iso_formatos_y_fallos():
    assert hp._iso("03/04/2025") == "2025-03-04"
    assert hp._iso("3/4/25") == "2025-03-04"
    assert hp._iso(" 12/31/2024 ") == "2024-12-31"
    assert hp._iso("2025-03-04") is None
    assert hp._iso("no es fecha") is None
    assert hp._iso(None) is None
    assert hp._iso("") is None


def test_parse_index_xml_year_no_numerica_queda_none():
    xml = """<FinancialDisclosure>
      <Member><FilingType>P</FilingType><DocID>2001234</DocID><Year>abcd</Year>
        <Last>Doe</Last><First>Jane</First><StateDst>CA05</StateDst>
        <FilingDate>03/04/2025</FilingDate></Member>
    </FinancialDisclosure>"""
    rows = hp.parse_index_xml(xml)
    assert rows == [{
        "doc_id": "2001234", "year": None, "last": "Doe", "first": "Jane",
        "prefix": "", "suffix": "", "state_district": "CA05", "state": "CA",
        "district": "05", "filing_date": "2025-03-04", "electronic": True,
    }]


def _zip_index(xml: str, name="2025FD.xml") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(name, xml)
    return buf.getvalue()


def test_fetch_index_descomprime_rellena_year_y_construye_url():
    xml = """<FinancialDisclosure>
      <Member><FilingType>P</FilingType><DocID>2001234</DocID><Year></Year>
        <Last>Doe</Last><First>Jane</First><StateDst>CA05</StateDst>
        <FilingDate>03/04/2025</FilingDate></Member>
      <Member><FilingType>C</FilingType><DocID>2009999</DocID><Year>2025</Year>
        <Last>Skip</Last><First>Me</First><StateDst>TX01</StateDst>
        <FilingDate>03/05/2025</FilingDate></Member>
    </FinancialDisclosure>"""
    client = _FakeClient(_zip_index(xml))
    rows = hp.fetch_index(2025, client)
    assert client.calls[0][0] == hp.INDEX_URL.format(year=2025)
    assert len(rows) == 1
    row = rows[0]
    assert row["year"] == 2025
    assert row["doc_id"] == "2001234"
    assert row["source_url"] == hp.PTR_URL.format(year=2025, doc_id="2001234")
    assert row["electronic"] is True


def test_fetch_ptr_pdf_valida_doc_id_y_devuelve_bytes():
    with pytest.raises(ValueError, match="DocID no numerico"):
        hp.fetch_ptr_pdf(2025, "abc")
    client = _FakeClient(b"%PDF-sintetico")
    assert hp.fetch_ptr_pdf(2025, "2001234", client) == b"%PDF-sintetico"
    assert client.calls[0][0] == hp.PTR_URL.format(year=2025, doc_id="2001234")


def test_parse_amount_sin_cifras_no_inventa():
    assert hp.parse_amount("  intercambio   sin importe ") == {
        "amount_text": "intercambio sin importe", "amount_min": None, "amount_max": None,
    }


def test_amount_midpoint_reglas():
    assert hp.amount_midpoint({}) is None
    assert hp.amount_midpoint({"amount_min": 1001}) == 1001
    assert hp.amount_midpoint({"amount_min": 1000, "amount_max": 5000}) == 3000
    assert hp.amount_midpoint({"amount_min": 1001, "amount_max": 2000}) == 1500.5


def test_parse_ptr_text_cuenta_bloque_no_parseado_al_llegar_meta():
    text = (
        "ID Owner Asset Transaction Type Date Notification Date Amount\n"
        "$200?\n"
        "Texto libre que no es una fila de operacion\n"
        "D : 03/01/2025\n"
    )
    result = hp.parse_ptr_text(text)
    assert result["unparsed_blocks"] == 1
    assert result["trades"] == []


@pytest.mark.parametrize(("text", "low", "high"), [
    ("$1,234.00", 1234, 1234),
    ("$1,234.0", 1234, 1234),
    ("$1,234.50", 1234, 1235),
    ("$1,234.01", 1234, 1235),
])
def test_importe_exacto_solo_redondea_si_hay_centimos(text, low, high):
    """Los ceros decimales no convierten un importe exacto en una horquilla."""
    parsed = hp.parse_amount(text)
    assert (parsed["amount_min"], parsed["amount_max"]) == (low, high)


@pytest.mark.parametrize("tail", ["", "\n* For the complete list of asset types, see instructions"])
def test_parse_ptr_cuenta_ultima_fila_ilegible(tail):
    text = (
        "ID Owner Asset Transaction Type Date Notification Date Amount\n"
        "$200?\n"
        "SP Empresa (ABC) [ST] P 03/01/2025 03/02/2025 importe ilegible"
        + tail
    )
    parsed = hp.parse_ptr_text(text)
    assert parsed["trades"] == []
    assert parsed["unparsed_blocks"] == 1


def test_parse_ptr_no_cuenta_comentario_final_como_fila_ilegible():
    text = (
        "ID Owner Asset Transaction Type Date Notification Date Amount\n"
        "$200?\n"
        "C : Comentario del declarante\n"
        "que sigue en otra linea\n"
    )
    assert hp.parse_ptr_text(text)["unparsed_blocks"] == 0


@pytest.mark.parametrize("owner", ["SP", "JT", "DC"])
@pytest.mark.parametrize("end", ["", "\nD : Nueva descripcion"])
def test_parse_ptr_fila_ilegible_tras_comentario(owner, end):
    text = (
        "ID Owner Asset Transaction Type Date Notification Date Amount\n"
        "$200?\nC : Comentario\ncontinuacion del comentario\n"
        f"{owner} Empresa (ABC) [ST] P 03/01/2025 03/02/2025 importe ilegible{end}"
    )
    parsed = hp.parse_ptr_text(text)
    assert parsed["trades"] == []
    assert parsed["unparsed_blocks"] == 1
