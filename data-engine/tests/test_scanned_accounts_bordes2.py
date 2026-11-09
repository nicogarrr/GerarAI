"""Bordes de app.services.scanned_accounts: extraccion, cache Redis y descarga (lote SA2).

extract_from_pdf se prueba con PdfPages y ocr falsos: demuestra el orquestado de pasadas,
estados y cache, NO la extraccion fiable de cuentas reales (sin tesseract ni pypdfium2
reales). Excepcion: test_extract_from_pdf_ocr_por_defecto_con_pdf_ilegible instancia el
PdfPages REAL para rechazar bytes que no son PDF (sigue sin haber OCR real). Redis y HTTP se doblan con clientes falsos de payloads literales: no hay red ni
servidor. monkeypatch solo sobre hooks del propio modulo (subprocess.run, PdfPages,
_tesseract disponible, _redis, extract_from_pdf, store_cached) y sobre httpx.Client en un
test; todo lo restaura monkeypatch.
"""

import json
from types import SimpleNamespace

import pytest

import app.services.scanned_accounts as sa

# ------------------------------------------------------------------------------ OCR real


def test_tesseract_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sa.shutil, "which", lambda _nombre: "/usr/bin/tesseract")
    assert sa.tesseract_available() is True
    monkeypatch.setattr(sa.shutil, "which", lambda _nombre: None)
    assert sa.tesseract_available() is False


def test_ocr_png_invoca_tesseract_sobre_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    llamadas = {}

    def run_falso(args: list[str], **kwargs: object) -> SimpleNamespace:
        llamadas["args"] = args
        llamadas["kwargs"] = kwargs
        return SimpleNamespace(stdout=b"texto le\xc3\xaddo y byte malo \xff")

    monkeypatch.setattr(sa.subprocess, "run", run_falso)
    assert sa.ocr_png(b"PNGDATA", psm="4") == "texto leído y byte malo �"
    assert llamadas["args"] == ["tesseract", "stdin", "stdout", "-l", "eng", "--psm", "4"]
    assert llamadas["kwargs"] == {
        "input": b"PNGDATA",
        "capture_output": True,
        "timeout": sa.OCR_TIMEOUT_S,
        "check": False,
    }


def test_ocr_png_psm_por_defecto(monkeypatch: pytest.MonkeyPatch) -> None:
    vistos = []
    monkeypatch.setattr(
        sa.subprocess, "run", lambda args, **kw: vistos.append(args) or SimpleNamespace(stdout=b"")
    )
    assert sa.ocr_png(b"x") == ""
    assert vistos[0][-1] == "6"


# --------------------------------------------------------------------- extract_from_pages


def _textos(mapa: dict[tuple[int, int], str]):
    llamadas: list[tuple[int, int]] = []

    def texts(pagina: int, pasada: int) -> str:
        llamadas.append((pagina, pasada))
        return mapa.get((pagina, pasada), "")

    return texts, llamadas


def test_extract_balance_en_dos_paginas() -> None:
    texts, _llamadas = _textos(
        {
            (5, 0): "Balance sheet\n2024 2023\nTotal assets 100 90",
            (6, 0): "Total liabilities 40 30\nTotal equity 60 60",
        }
    )
    resultado = sa.extract_from_pages(texts, {sa.BALANCE: [(5, True, "Balance sheet")]}, 6)
    assert resultado["checks"]["balance"]["ok"] is True
    assert resultado["statements"]["balance"]["pages"] == [5, 6]
    assert resultado["statements"]["balance"]["ocr_pass"] == "300 ppp, psm 6"
    assert [f["metric"] for f in resultado["figures"]] == [
        "total_equity",
        "equity_attributable",
        "net_assets",
    ]


def test_extract_income_sin_pbt_no_reintenta_pasadas() -> None:
    texts, llamadas = _textos(
        {(4, 0): "Statement of comprehensive income\n2024 2023\nTotal comprehensive income 50 40"}
    )
    resultado = sa.extract_from_pages(texts, {sa.INCOME: [(4, True, "Income statement")]}, 9)
    # Sin «profit before tax» en la pasada 0 se descarta sin gastar mas OCR.
    assert llamadas == [(4, 0), (4, 0)]
    assert resultado["checks"]["income"] == {
        "ok": False,
        "why": "no se leen el beneficio antes de impuestos y el del ejercicio",
        "pages": [4],
    }
    assert resultado["statements"]["income"]["ocr_pass"] == "300 ppp, psm 6"


def test_extract_income_que_nunca_cuadra_agota_las_tres_pasadas() -> None:
    texto = (
        "Income statement\n2024 2023\nProfit before taxation 100 90\n"
        "Taxation 20 15\nProfit for the year 50 40"
    )
    texts, llamadas = _textos({(7, 0): texto, (7, 1): texto, (7, 2): texto})
    resultado = sa.extract_from_pages(texts, {sa.INCOME: [(7, True, "Income statement")]}, 9)
    assert llamadas == [(7, 0), (7, 0), (7, 1), (7, 2)]
    assert resultado["checks"]["income"]["ok"] is False
    assert resultado["checks"]["income"]["why"] == (
        "no cuadra: antes de impuestos 100, impuesto 20, beneficio del ejercicio 50"
    )
    # Se conserva la primera lectura aunque ninguna pasada cuadre.
    assert resultado["statements"]["income"]["pages"] == [7]


# ----------------------------------------------------------------------- extract_from_pdf


class _PaginasFalsas:
    """PdfPages de mentira: png() devuelve bytes que codifican (indice, dpi, fraccion)."""

    instancias: list["_PaginasFalsas"] = []

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.cerrado = False
        type(self).instancias.append(self)

    def __len__(self) -> int:
        return 2

    def png(self, index: int, dpi: int, top_fraction: float | None = None) -> bytes:
        return f"png:{index}:{dpi}:{top_fraction}".encode()

    def close(self) -> None:
        self.cerrado = True


@pytest.fixture
def paginas_falsas(monkeypatch: pytest.MonkeyPatch) -> list[_PaginasFalsas]:
    """Monta _PaginasFalsas y una lista de instancias fresca; monkeypatch restaura ambas."""
    instancias: list[_PaginasFalsas] = []
    monkeypatch.setattr(_PaginasFalsas, "instancias", instancias)
    monkeypatch.setattr(sa, "PdfPages", _PaginasFalsas)
    return instancias


def test_extract_from_pdf_sin_tesseract_forzado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sa, "tesseract_available", lambda: False)
    assert sa.extract_from_pdf(b"pdf", ocr=None) == {
        "status": "unavailable",
        "reason": "sin tesseract en este servidor",
        "figures": [],
    }


def test_extract_from_pdf_ilegible(monkeypatch: pytest.MonkeyPatch) -> None:
    def paginas_rotas(data: bytes) -> object:
        raise ValueError("boom")

    monkeypatch.setattr(sa, "PdfPages", paginas_rotas)
    resultado = sa.extract_from_pdf(b"no es un pdf", ocr=lambda png, psm="6": "")
    assert resultado == {"status": "unavailable", "reason": "PDF ilegible: ValueError", "figures": []}


def test_extract_from_pdf_demasiadas_paginas(
    paginas_falsas: list[_PaginasFalsas], monkeypatch: pytest.MonkeyPatch
) -> None:
    class Cinco(_PaginasFalsas):
        def __len__(self) -> int:
            return 5

    monkeypatch.setattr(sa, "PdfPages", Cinco)
    resultado = sa.extract_from_pdf(b"pdf", ocr=lambda png, psm="6": "", max_pages=2)
    assert resultado == {"status": "unavailable", "reason": "5 paginas (> 2)", "figures": []}


def test_extract_from_pdf_parcial_con_ocr_falso(paginas_falsas: list[_PaginasFalsas]) -> None:
    cabeceras = {
        b"png:0:144:0.22": "Income statement\nyear ended 31 December 2024",
        b"png:1:144:0.22": "Notes to the accounts",
    }
    cuenta = (
        "Income statement\n2024 2023\nProfit before taxation 100 90\n"
        "Taxation 20 15\nProfit for the year 50 40"
    )
    llamadas_ocr: list[tuple[bytes, str]] = []

    def ocr_falso(png: bytes, psm: str = "6") -> str:
        llamadas_ocr.append((png, psm))
        return cabeceras.get(png, cuenta)

    resultado = sa.extract_from_pdf(b"pdf", ocr=ocr_falso)

    assert resultado["status"] == "partial"
    assert resultado["reason"] == (
        "income: no cuadra: antes de impuestos 100, impuesto 20, beneficio del ejercicio 50"
    )
    assert resultado["page_count"] == 2
    assert resultado["extractor_version"] == sa.EXTRACTOR_VERSION
    assert resultado["extracted_at"].endswith("Z")
    assert resultado["statements"]["balance"] is None
    assert resultado["statements"]["income"]["pages"] == [1]
    assert resultado["statements"]["income"]["ocr_pass"] == "300 ppp, psm 6"
    assert llamadas_ocr == [
        (b"png:0:144:0.22", "6"),
        (b"png:1:144:0.22", "6"),
        (b"png:0:300:None", "6"),
        (b"png:0:300:None", "4"),
        (b"png:0:200:None", "6"),
    ]
    assert paginas_falsas[0].cerrado is True


# -------------------------------------------------------------------------- cache Redis


class _RedisFalso:
    def __init__(self, **respuestas: object) -> None:
        self.respuestas = respuestas
        self.llamadas: list[tuple] = []

    def _resp(self, clave: str) -> object:
        valor = self.respuestas.get(clave)
        if isinstance(valor, Exception):
            raise valor
        return valor

    def get(self, clave: str) -> object:
        self.llamadas.append(("get", clave))
        return self._resp("get")

    def set(self, *args: object, **kwargs: object) -> object:
        self.llamadas.append(("set", args, kwargs))
        return self._resp("set")

    def delete(self, *args: object) -> int:
        self.llamadas.append(("delete", args))
        return 1

    def hset(self, *args: object) -> int:
        self.llamadas.append(("hset", args))
        return 1

    def expire(self, *args: object) -> bool:
        self.llamadas.append(("expire", args))
        return True

    def hvals(self, clave: str) -> object:
        self.llamadas.append(("hvals", clave))
        return self._resp("hvals")

    def mget(self, claves: list[str]) -> object:
        self.llamadas.append(("mget", claves))
        return self._resp("mget")


def test_cache_key() -> None:
    assert sa.cache_key("12345678", "2024-12-31") == "ch:scanned:v1:12345678:2024-12-31"
    assert sa.cache_key("12345678", None) == "ch:scanned:v1:12345678:sf"


def test_load_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _RedisFalso(get=b'{"status": "ok", "figures": []}')
    monkeypatch.setattr(sa, "_redis", lambda: cliente)
    assert sa.load_cached("12345678", None) == {"status": "ok", "figures": []}
    assert cliente.llamadas == [("get", "ch:scanned:v1:12345678:sf")]


def test_load_cached_sin_redis_sin_valor_y_con_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sa, "_redis", lambda: None)
    assert sa.load_cached("12345678", "2024-12-31") is None
    monkeypatch.setattr(sa, "_redis", lambda: _RedisFalso(get=None))
    assert sa.load_cached("12345678", "2024-12-31") is None
    monkeypatch.setattr(sa, "_redis", lambda: _RedisFalso(get=ConnectionError("caido")))
    assert sa.load_cached("12345678", "2024-12-31") is None


def test_store_cached_con_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _RedisFalso()
    monkeypatch.setattr(sa, "_redis", lambda: cliente)
    sa.store_cached(
        "12345678",
        "2024-12-31",
        {"status": "ok", "figures": [{"metric": "cash", "value": 10.0}]},
        ticker="acme",
        company_name="Acme plc",
        document_url="https://doc",
    )
    clave = "ch:scanned:v1:12345678:2024-12-31"
    assert [ll[0] for ll in cliente.llamadas] == ["set", "delete", "hset", "expire"]
    _, (k, payload), kwargs = cliente.llamadas[0]
    assert k == clave
    assert kwargs == {"ex": 15_552_000}
    assert json.loads(payload) == {
        "status": "ok",
        "figures": [{"metric": "cash", "value": 10.0}],
        "company_number": "12345678",
        "company_name": "Acme plc",
        "made_up_to": "2024-12-31",
        "document_url": "https://doc",
    }
    assert cliente.llamadas[1] == ("delete", (clave + ":pending",))
    assert cliente.llamadas[2] == ("hset", ("ch:scanned:v1:ticker:ACME", "12345678", clave))
    assert cliente.llamadas[3] == ("expire", ("ch:scanned:v1:ticker:ACME", 15_552_000))


def test_store_cached_sin_ticker_sin_redis_y_con_error(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _RedisFalso()
    monkeypatch.setattr(sa, "_redis", lambda: cliente)
    sa.store_cached("12345678", None, {"status": "ok"})
    assert [ll[0] for ll in cliente.llamadas] == ["set", "delete"]
    monkeypatch.setattr(sa, "_redis", lambda: None)
    sa.store_cached("12345678", None, {"status": "ok"})
    monkeypatch.setattr(sa, "_redis", lambda: _RedisFalso(set=ConnectionError("caido")))
    sa.store_cached("12345678", None, {"status": "ok"})  # no propaga


def test_claim_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _RedisFalso(set=True)
    monkeypatch.setattr(sa, "_redis", lambda: cliente)
    assert sa.claim_pending("12345678", None) is True
    assert cliente.llamadas == [("set", ("ch:scanned:v1:12345678:sf:pending", "1"), {"nx": True, "ex": 7200})]
    monkeypatch.setattr(sa, "_redis", lambda: _RedisFalso(set=None))
    assert sa.claim_pending("12345678", None) is False
    monkeypatch.setattr(sa, "_redis", lambda: None)
    assert sa.claim_pending("12345678", None) is False
    monkeypatch.setattr(sa, "_redis", lambda: _RedisFalso(set=ConnectionError("caido")))
    assert sa.claim_pending("12345678", None) is False


def test_for_ticker_ordenado(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _RedisFalso(
        hvals=[b"k2", b"k1"],
        mget=[
            json.dumps({"company_name": "Zeta", "made_up_to": "2024-12-31"}),
            json.dumps({"company_name": "Acme", "made_up_to": "2023-12-31"}),
        ],
    )
    monkeypatch.setattr(sa, "_redis", lambda: cliente)
    resultado = sa.for_ticker("acme")
    assert [r["company_name"] for r in resultado] == ["Acme", "Zeta"]
    assert cliente.llamadas[0] == ("hvals", "ch:scanned:v1:ticker:ACME")
    assert cliente.llamadas[1] == ("mget", ["k2", "k1"])


def test_for_ticker_vacio_sin_redis_y_con_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sa, "_redis", lambda: _RedisFalso())
    assert sa.for_ticker("") == []
    monkeypatch.setattr(sa, "_redis", lambda: None)
    assert sa.for_ticker("ACME") == []
    monkeypatch.setattr(sa, "_redis", lambda: _RedisFalso(hvals=ConnectionError("caido")))
    assert sa.for_ticker("ACME") == []


def test_page_url() -> None:
    assert sa.page_url(None, 3) is None
    assert sa.page_url("https://doc", None) == "https://doc"
    assert sa.page_url("https://doc#frag", 7) == "https://doc#page=7"


# ------------------------------------------------------------------------------ descarga

_CH = "https://find-and-update.company-information.service.gov.uk/company/00000001/filing-history/x/document?format=pdf"
_S3 = "https://document-api-images.s3.amazonaws.com/bucket/file.pdf?X-Amz-Signature=1"


def _resp(estado: int, contenido: bytes = b"", location: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=estado,
        headers={"location": location} if location else {},
        content=contenido,
    )


class _HttpFalso:
    def __init__(self, respuestas: list[SimpleNamespace]) -> None:
        self.respuestas = list(respuestas)
        self.urls: list[str] = []
        self.cerrado = False

    def get(self, url: str) -> SimpleNamespace:
        self.urls.append(url)
        return self.respuestas.pop(0)

    def close(self) -> None:
        self.cerrado = True


def test_descarga_url_no_permitida() -> None:
    http = _HttpFalso([])
    with pytest.raises(ValueError) as excinfo:
        sa.download_public_pdf("https://evil.example.com/x.pdf", client=http)
    assert str(excinfo.value) == "la URL no es un documento de Companies House"
    assert http.urls == []


def test_descarga_sigue_redirect_a_s3_firmado() -> None:
    http = _HttpFalso([_resp(302, location=_S3), _resp(200, contenido=b"%PDF-1.4")])
    assert sa.download_public_pdf(_CH, client=http) == b"%PDF-1.4"
    assert http.urls == [_CH, _S3]
    assert http.cerrado is False  # cliente ajeno: no se cierra


def test_descarga_redirect_fuera_de_companies_house() -> None:
    http = _HttpFalso([_resp(302, location="https://evil.example.com/x.pdf")])
    with pytest.raises(ValueError) as excinfo:
        sa.download_public_pdf(_CH, client=http)
    assert str(excinfo.value) == "redireccion fuera de Companies House"


def test_descarga_estado_no_200() -> None:
    http = _HttpFalso([_resp(404)])
    with pytest.raises(ValueError) as excinfo:
        sa.download_public_pdf(_CH, client=http)
    assert str(excinfo.value) == "documento 404"


def test_descarga_demasiado_grande() -> None:
    http = _HttpFalso([_resp(200, contenido=b"1234")])
    with pytest.raises(ValueError) as excinfo:
        sa.download_public_pdf(_CH, client=http, max_bytes=3)
    assert str(excinfo.value) == "documento demasiado grande"


def test_descarga_cliente_propio_se_cierra(monkeypatch: pytest.MonkeyPatch) -> None:
    http = _HttpFalso([_resp(200, contenido=b"%PDF")])
    creados: list[dict] = []

    def cliente_httpx(**kwargs: object) -> _HttpFalso:
        creados.append(kwargs)
        return http

    monkeypatch.setattr("httpx.Client", cliente_httpx)
    assert sa.download_public_pdf(_CH) == b"%PDF"
    assert creados == [
        {
            "timeout": 60.0,
            "follow_redirects": False,
            "headers": {"User-Agent": "GerarAI/1.0 (tab@tab.bot)", "Accept": "application/pdf"},
        }
    ]
    assert http.cerrado is True


# --------------------------------------------------------------------------- read_and_cache


def test_read_and_cache_guarda_lo_leido(monkeypatch: pytest.MonkeyPatch) -> None:
    guardadas: list[tuple] = []
    monkeypatch.setattr(sa, "extract_from_pdf", lambda data: {"status": "ok", "figures": []})
    monkeypatch.setattr(sa, "store_cached", lambda *a, **kw: guardadas.append((a, kw)))
    resultado = sa.read_and_cache(
        "12345678",
        "2024-12-31",
        "https://doc",
        ticker="ACME",
        company_name="Acme",
        fetch=lambda url: b"PDF",
    )
    assert resultado == {"status": "ok", "figures": []}
    assert guardadas == [
        (
            ("12345678", "2024-12-31", {"status": "ok", "figures": []}),
            {"ticker": "ACME", "company_name": "Acme", "document_url": "https://doc"},
        )
    ]


def test_read_and_cache_no_guarda_si_no_hay_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    guardadas: list[tuple] = []
    monkeypatch.setattr(sa, "extract_from_pdf", lambda data: {"status": "unavailable", "figures": []})
    monkeypatch.setattr(sa, "store_cached", lambda *a, **kw: guardadas.append((a, kw)))
    resultado = sa.read_and_cache("12345678", None, "https://doc", fetch=lambda url: b"PDF")
    assert resultado == {"status": "unavailable", "figures": []}
    assert guardadas == []


def test_extract_balance_en_dos_paginas_que_tampoco_cuadra() -> None:
    texts, llamadas = _textos(
        {
            (5, 0): "Balance sheet\n2024 2023\nTotal assets 100 90",
            (6, 0): "Total liabilities 50 30\nTotal equity 60 60",
        }
    )
    resultado = sa.extract_from_pages(texts, {sa.BALANCE: [(5, True, "Balance sheet")]}, 6)
    # La lectura combinada tampoco cuadra (100 != 50 + 60): se prueban las tres pasadas.
    assert llamadas == [(5, 0), (5, 0), (6, 0), (5, 1), (6, 1), (5, 2), (6, 2)]
    assert resultado["checks"]["balance"] == {
        "ok": False,
        "why": "no se leen los totales del balance (activo, pasivo, patrimonio)",
        "pages": [5],
    }


def test_extract_from_pdf_ocr_por_defecto_con_pdf_ilegible(monkeypatch: pytest.MonkeyPatch) -> None:
    # Con tesseract disponible el ocr por defecto es ocr_png; el PDF ilegible se detecta antes
    # de invocarlo. El tipo exacto de la excepcion depende de pypdfium2: no se fija.
    monkeypatch.setattr(sa, "tesseract_available", lambda: True)
    resultado = sa.extract_from_pdf(b"esto no es un pdf", ocr=None)
    assert resultado["status"] == "unavailable"
    assert resultado["reason"].startswith("PDF ilegible: ")
    assert resultado["figures"] == []


def test_redis_es_el_cliente_compartido_de_app_core(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import cache

    centinela = object()
    monkeypatch.setattr(cache, "_redis_client", lambda: centinela)  # noqa: SLF001
    assert sa._redis() is centinela  # noqa: SLF001 - delega en el getter compartido


def test_descarga_tres_redirects_agotan_el_bucle() -> None:
    http = _HttpFalso([_resp(302, location=_S3) for _ in range(4)])
    with pytest.raises(ValueError) as excinfo:
        sa.download_public_pdf(_CH, client=http)
    assert str(excinfo.value) == "documento 302"
    assert http.urls == [_CH, _S3, _S3, _S3]


# ------------------------------------------------------------------------ cabos sueltos


def test_parse_statement_sin_anos_en_ninguna_parte() -> None:
    st = sa.parse_statement(sa.BALANCE, [(1, "Balance sheet\nSin fechas\nTurnover 1,000")])
    assert st.years == []
    assert st.current_col is None
    assert st.period_end is None


def test_figures_balance_con_minoritarios_no_iguala_atribuible() -> None:
    balance = sa.Statement(
        kind=sa.BALANCE,
        pages=[9],
        title="t",
        consolidated=True,
        currency="GBP",
        scale=1_000,
        unit="£'000",
        years=[2024, 2023],
        current_col=0,
        period_end="2024-12-31",
        rows=[
            sa.Row("Total assets", [sa.Decimal("100")], "Total assets 100", 0, 9),
            sa.Row("Total liabilities", [sa.Decimal("40")], "Total liabilities 40", 1, 9),
            sa.Row("Total equity", [sa.Decimal("60")], "Total equity 60", 2, 9),
            sa.Row("Non-controlling interests", [sa.Decimal("5")], "Non-controlling interests 5", 3, 9),
        ],
    )
    resultado = sa.figures_from_statements(None, balance)
    assert resultado["checks"]["balance"]["ok"] is True
    assert [f["metric"] for f in resultado["figures"]] == ["total_equity", "net_assets"]
