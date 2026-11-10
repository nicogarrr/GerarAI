"""Bordes de app/services/official_catalysts.py (zona levantada por Nico 9-nov-2026 18:43).

La suite existente cubre el camino feliz con la nota real de Rakuten (fixture). Aquí se cubren los
bordes puros y las rutas de lectura/recogida con dobles (sin red):

- Catalyst.as_dict, _host (URL rota), registrable_label (segundos niveles), official_kind (sin https,
  sin host, sec, wire por subdominio, medio con ruta de sala de prensa, ir por etiqueta registrable,
  corporativa con y sin nombre en el texto);
- company_terms (sufijos societarios, the/and, ticker con bolsa, vacío);
- _standalone y _mentions (nombre pegado a otro, conectores permitidos, sufijo 株式会社, término no ASCII);
- sentences (filtro de longitud), _currency (todas las divisas), amount_value (formatos de miles,
  multiplicadores 兆/億/万/mil millones/thousand/bn/mn, sufijos m/b, float inválido);
- attributable (EN receptor, JA は/が + 受注, importe...to Empresa, no atribuible);
- extract (sin mención, frase sin mención en wire, importe sin dígitos, atribución solo primera por tipo,
  frase de participación 51%/49% preferida, recorte a MAX_SUMMARY);
- _published, _ir_hosts, catalysts_for (error con rollback, sin texto, 10-K fuera, 8-K por metadatos o
  por título, medio fuera, dedup por hash, orden por fecha);
- page_text (HTML roto), page_date (ventana del titular, fecha dentro del titular, fecha inválida,
  metadatos, fecha de ruta, ruta inválida, sin fecha);
- discover (una consulta caída no para las demás), _default_fetch, _robots_allows (sin robots se
  permite, disallow);
- collect (prefiltro sin descarga, dedup, ya archivada, tope de páginas, robots, error de descarga,
  página sin mención, fecha de la página vs buscador, troceo en chunks, NewsEvent roto).
"""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from app.services import analyst_press_estimates as ape
from app.services import official_catalysts as oc
from app.services import public_fetch as pf

ASTS = SimpleNamespace(
    id=1, name="AST SpaceMobile, Inc.", ticker="ASTS", ir_url="https://investors.ast-science.com"
)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _DB:
    def __init__(self, queue=()):
        self._queue = list(queue)
        self.added = []
        self.flushed = 0
        self.rolled_back = False

    def scalars(self, _stmt):
        return _Rows(self._queue.pop(0))

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flushed += 1

    def rollback(self):
        self.rolled_back = True


# --- piezas pequeñas ----------------------------------------------------------


def test_catalyst_as_dict_convierte_amounts_y_etiqueta():
    cat = oc.Catalyst(
        date="2026-01-02",
        kind="jv",
        url="u",
        publisher="p",
        source_kind="wire",
        summary="s",
        amounts=("1", "2"),
    )
    d = cat.as_dict()
    assert d["amounts"] == ["1", "2"] and d["kind_label"] == "empresa conjunta (JV)"
    assert (
        oc.Catalyst(date=None, kind="otro", url="u", publisher="p", source_kind="x", summary="s").as_dict()[
            "kind_label"
        ]
        == "otro"
    )


def test_host_roto_devuelve_vacio():
    assert oc._host("http://[::1") == ""
    assert oc._host("notaurl") == ""


def test_registrable_label_segundos_niveles():
    assert oc.registrable_label("corp.rakuten.co.jp") == "rakuten"
    assert oc.registrable_label("investors.ast-science.com") == "ast-science"
    assert oc.registrable_label("example.co.uk") == "example"
    assert oc.registrable_label("localhost") is None
    assert oc.registrable_label("a.b.com") == "b"


def test_official_kind_bordes():
    assert oc.official_kind("http://www.sec.gov/x") is None  # sin https
    assert oc.official_kind("https://") is None  # sin host
    assert oc.official_kind("https://sec.gov/Archives/edgar/x") == "sec"
    assert oc.official_kind("https://news.businesswire.com/x") == "wire"  # subdominio de wire
    # Un medio con ruta de sala de prensa nunca es oficial:
    assert oc.official_kind("https://www.reuters.com/press/releases/x", text="reuters") is None
    # ir también por etiqueta registrable equivalente (ir.ast-science.com = investors.ast-science.com):
    assert (
        oc.official_kind("https://ir.ast-science.com/anything", ir_hosts=["investors.ast-science.com"])
        == "ir"
    )
    assert (
        oc.official_kind("https://investors.ast-science.com/x", ir_hosts=["investors.ast-science.com"])
        == "ir"
    )
    # Corporativa: ruta de sala de prensa + la editora nombrada en el texto:
    url = "https://corp.rakuten.co.jp/news/press/2026/1109_01.html"
    assert oc.official_kind(url, text="Rakuten Group") == "corporativa"
    assert oc.official_kind(url, text="no se nombra a nadie") is None
    # Etiqueta de 3 caracteres justo en la frontera (>= 3): entra si la nombra el texto:
    assert oc.official_kind("https://www.abc.com/newsroom/x", text="ABC anuncia") == "corporativa"
    assert oc.official_kind("https://www.ab.com/newsroom/x", text="AB anuncia") is None  # etiqueta < 3


def test_company_terms_sufijos_palabras_y_ticker():
    terms = oc.company_terms(SimpleNamespace(name="AST SpaceMobile, Inc.", ticker="ASTS"))
    assert terms == ["AST SpaceMobile", "AST", "SpaceMobile", "ASTS"]
    assert oc.company_terms(SimpleNamespace(name="The Boeing Company", ticker="BA")) == [
        "The Boeing Company",
        "Boeing",
        "Company",
        "BA",
    ]
    assert oc.company_terms(SimpleNamespace(name="", ticker="ASML.AS")) == ["ASML"]
    assert oc.company_terms(SimpleNamespace(name=None, ticker=None)) == []


def test_standalone_y_mentions_bordes():
    terms = ["AST"]
    # Pegado a otro nombre propio no es mención independiente:
    assert oc._mentions("Rakuten AST recibe", terms) and not oc.attributable(
        "Rakuten AST recibe 100億円", (18, 24), terms
    )
    # Tras conector permitido sí:
    text = "Contrato para AST firmado"
    start = text.index("AST")
    assert oc._standalone(text, start, start + 3) is True
    # Sufijo societario japonés pegado:
    assert oc._standalone("AST株式会社", 0, 3) is False
    # Término ASCII exige fronteras: no casa dentro de ASTX:
    assert oc._mentions("ASTX lanzó", ["AST"]) == []
    # Término no ASCII sin fronteras:
    assert oc._mentions("楽天は発表", ["楽天"]) == [(0, 2)]
    assert oc._mentions("nada", ["", "AST"]) == []


def test_sentences_filtra_longitudes():
    buena = "Esta frase tiene la longitud suficiente para quedarse."
    larga = "Esta frase supera con creces el limite permitido " + "x" * 1500
    got = oc.sentences("Muy corta.\n" + buena + "\n" + larga)
    assert got == [buena]
    assert oc.sentences("") == [] and oc.sentences(None) == []


def test_currency_todas_las_ramificaciones():
    assert oc._currency("1,480億円") == "JPY"
    assert oc._currency("JPY 148 billion") == "JPY"
    assert oc._currency("€30m") == "EUR"
    assert oc._currency("£5 million") == "GBP"
    assert oc._currency("C$10 million") == "CAD"
    assert oc._currency("A$10 million") == "AUD"
    assert oc._currency("$43 million") == "USD"
    assert oc._currency("100 dólares") == "USD"
    assert oc._currency("sin símbolo 100") is None


def test_amount_value_formatos_y_multiplicadores():
    assert oc.amount_value("sin dígitos") is None
    assert oc.amount_value("1,480億円") == 1.48e11
    assert oc.amount_value("1.2兆円") == 1.2e12
    assert oc.amount_value("1万円") == 1e4
    assert oc.amount_value("1.480,5 millones") == 1480.5e6  # formato europeo
    assert oc.amount_value("2.5bn") == 2.5e9
    assert oc.amount_value("3 mn") == 3e6
    assert oc.amount_value("500 thousand") == 5e5
    assert oc.amount_value("1,5 mil millones") == 1.5e9
    assert oc.amount_value("€30m") == 30e6
    assert oc.amount_value("$2b") == 2e9
    assert oc.amount_value("42") == 42.0
    assert oc.amount_value("1.2.3") is None  # float inválido


def test_attributable_los_tres_idiomas_y_el_no():
    terms = oc.company_terms(ASTS)
    s_en = "AST SpaceMobile was awarded a contract valued at $43 million."
    m = list(oc._AMOUNT.finditer(s_en))[0]
    assert oc.attributable(s_en, (m.start(), m.end()), terms) is True
    s_to = "A grant of $43 million was approved for AST SpaceMobile."
    m = list(oc._AMOUNT.finditer(s_to))[0]
    assert oc.attributable(s_to, (m.start(), m.end()), terms) is True
    s_ja = "ASTが1,480億円の補助金を受ける契約"
    m = list(oc._AMOUNT.finditer(s_ja))[0]
    assert oc.attributable(s_ja, (m.start(), m.end()), terms) is True
    s_no = "Rakuten recibe 100億円 y AST mira."
    m = list(oc._AMOUNT.finditer(s_no))[0]
    assert oc.attributable(s_no, (m.start(), m.end()), terms) is False


# --- extract ------------------------------------------------------------------


def test_extract_sin_texto_o_sin_mencion():
    terms = oc.company_terms(ASTS)
    assert oc.extract("", terms=terms, published=None, url="u", publisher="p", source_kind="wire") == []
    assert (
        oc.extract(
            "No hay ninguna empresa aquí, solo agreement y contract largos.",
            terms=terms,
            published=None,
            url="u",
            publisher="p",
            source_kind="wire",
        )
        == []
    )


def test_extract_wire_exige_mencion_por_frase_y_dedup_atribucion():
    terms = oc.company_terms(ASTS)
    text = (
        "Rakuten announced an agreement with a supplier yesterday morning. "
        "AST SpaceMobile signed a contract worth $43 million with the Agency. "
        "AST SpaceMobile signed a $10 million supply contract with the Agency last Friday."
    )
    [c] = oc.extract(
        text,
        terms=terms,
        published=date(2026, 1, 2),
        url="https://www.businesswire.com/x",
        publisher="www.businesswire.com",
        source_kind="wire",
    )
    assert c.kind == "contrato"
    # La frase sin mención no entra; la atribución se queda con el primer importe atribuido:
    assert c.amount_for_company == "$43 million"
    assert c.amount_for_company_value == 43e6 and c.amount_currency == "USD"
    assert "$43 million" in c.amounts and "$10 million" in c.amounts
    assert c.amount_reason == "atribuido a la empresa en la misma frase"
    assert c.date == "2026-01-02"


def test_extract_sec_no_exige_mencion_en_cada_frase_y_prefiere_participacion():
    terms = oc.company_terms(ASTS)
    text = (
        "The parties formed a joint venture last week after long talks. "
        "The joint venture will be owned 51% by Rakuten and 49% by AST SpaceMobile."
    )
    [c] = oc.extract(
        text,
        terms=terms,
        published=None,
        url="https://www.sec.gov/Archives/x",
        publisher="www.sec.gov",
        source_kind="sec",
        document_id=7,
        title="8-K",
    )
    assert c.kind == "jv" and "51%" in c.summary and "49%" in c.summary
    assert c.date is None and c.document_id == 7 and c.title == "8-K"
    assert c.amount_reason == oc.ND_AMOUNT


def test_extract_recorta_frases_largas():
    terms = oc.company_terms(ASTS)
    larga = "AST SpaceMobile signed a contract " + "x" * 500
    [c] = oc.extract(
        larga,
        terms=terms,
        published=None,
        url="https://www.sec.gov/x",
        publisher="www.sec.gov",
        source_kind="sec",
    )
    assert len(c.summary) <= oc.MAX_SUMMARY + 1 and c.summary.endswith("…")


# --- lectura de documentos guardados -------------------------------------------


def test_published_e_ir_hosts():
    assert oc._published(SimpleNamespace(published_at=datetime(2026, 1, 2, 10, tzinfo=UTC))) == date(
        2026, 1, 2
    )
    assert oc._published(SimpleNamespace(published_at=date(2026, 1, 2))) == date(2026, 1, 2)
    assert oc._published(SimpleNamespace(published_at=None)) is None
    assert oc._published(SimpleNamespace(published_at="2026-01-02")) is None
    assert oc._ir_hosts(SimpleNamespace(ir_url="https://investors.ast-science.com")) == [
        "investors.ast-science.com"
    ]
    assert oc._ir_hosts(SimpleNamespace(ir_url=None)) == []


def _doc(i, url, text, *, form=None, title=None, days_ago=10):
    return SimpleNamespace(
        id=i,
        source_url=url,
        metadata_={"form": form} if form else {},
        title=title,
        published_at=datetime.combine(
            date(2026, 11, 9) - timedelta(days=days_ago), datetime.min.time(), tzinfo=UTC
        ),
        _text=text,
    )


def test_catalysts_for_error_devuelve_vacio_y_rollback():
    class DBrota(_DB):
        def scalars(self, _stmt):
            raise RuntimeError("sin tabla documents")

    db = DBrota()
    assert oc.catalysts_for(db, ASTS, today=date(2026, 11, 9)) == []
    assert db.rolled_back is True


def test_catalysts_for_flujo_completo():
    contrato = "AST SpaceMobile signed a definitive agreement with the Agency yesterday afternoon."
    docs = [
        _doc(1, "https://www.sec.gov/Archives/edgar/data/1/1.htm", contrato, form="10-K"),  # periódico: fuera
        _doc(
            2, "https://www.sec.gov/Archives/edgar/data/1/2.htm", contrato, form="8-K"
        ),  # entra por metadatos
        _doc(3, "https://www.sec.gov/Archives/edgar/data/1/3.htm", contrato, title="8-K"),  # entra por título
        _doc(4, "https://www.reuters.com/news/x", contrato),  # medio: fuera
        _doc(5, "https://www.sec.gov/Archives/edgar/data/1/5.htm", "", form="8-K"),  # sin texto: fuera
        _doc(
            6, "https://www.sec.gov/Archives/edgar/data/1/2.htm", contrato, form="8-K", days_ago=5
        ),  # duplicado
    ]
    queue = [docs] + [[d._text] for d in docs]
    db = _DB(queue)
    out = oc.catalysts_for(db, ASTS, today=date(2026, 11, 9))
    urls = [c["url"] for c in out]
    # Misma fecha (2026-10-30): el desempate es document_id descendente (3 antes que 2):
    assert urls == [
        "https://www.sec.gov/Archives/edgar/data/1/3.htm",
        "https://www.sec.gov/Archives/edgar/data/1/2.htm",
    ]
    assert out[0]["date"] == "2026-10-30" and out[0]["kind"] == "contrato"


def test_catalysts_for_viejo_fuera_de_ventana():
    docs = [
        _doc(
            1,
            "https://www.sec.gov/Archives/edgar/data/1/1.htm",
            "AST SpaceMobile signed a definitive agreement with the Agency yesterday afternoon.",
            form="8-K",
            days_ago=400,
        )
    ]
    db = _DB([[]])  # la consulta SQL filtra por fecha; la fake devuelve vacío
    assert oc.catalysts_for(db, ASTS, today=date(2026, 11, 9)) == []


# --- página: texto y fecha ------------------------------------------------------


def test_page_text_html_roto():
    assert oc.page_text(b"") == ("", None, "")


def test_page_date_ventana_titular_y_exclusiones():
    h1 = "Rakuten and AST Sign Agreement"
    # Fecha ISO delante del titular:
    assert oc.page_date("Publicado el 2026-11-09. " + h1, h1, "https://x.example.com/a") == date(2026, 11, 9)
    # Una fecha dentro del propio titular no cuenta; gana la de fuera:
    h1_con_fecha = "Q3 Results 2026-11-05"
    assert oc.page_date(
        h1_con_fecha + " text 2026-11-09 after title", h1_con_fecha, "https://x.example.com/a"
    ) == date(2026, 11, 9)
    # La fecha más cercana al titular gana (la posterior está más lejos):
    flat = "November 9, 2026 " + h1 + " " + "x" * 100 + " 2026-01-02"
    assert oc.page_date(flat, h1, "https://x.example.com/a") == date(2026, 11, 9)
    # Sin titular no hay ventana:
    assert oc.page_date(flat, None, "https://x.example.com/a") is None
    # Fecha inválida en la ventana se descarta:
    assert oc.page_date("2026-13-99 " + h1, h1, "https://x.example.com/a") is None


def test_page_date_metadatos_y_ruta():
    html = (
        b'<html><head><meta property="article:published_time" content="2026-03-04T10:00:00Z"></head></html>'
    )
    assert oc.page_date("sin fechas de texto", None, "https://x.example.com/a", html) == date(2026, 3, 4)
    assert oc.page_date("nada", None, "https://corp.example.com/news/2026/1109_01.html") == date(2026, 11, 9)
    assert (
        oc.page_date("nada", None, "https://corp.example.com/news/2026/1332_01.html") is None
    )  # fecha inválida
    assert oc.page_date("nada", None, "https://corp.example.com/news/x") is None


# --- descubrimiento y robots -----------------------------------------------------


def test_discover_una_consulta_caida_no_para_las_demas(monkeypatch):
    monkeypatch.setattr(ape, "bing_items", lambda rss: [("https://www.businesswire.com/x", "t", None)])
    calls = []

    def fetch(url):
        calls.append(url)
        if len(calls) == 2:
            raise RuntimeError("bing caído")
        return b"<rss/>"

    out = oc.discover(ASTS, fetch)
    assert len(calls) == 4  # las 4 consultas se intentan
    assert out == [("https://www.businesswire.com/x", "t", None)] * 3


def test_discover_sin_nombre_usa_ticker(monkeypatch):
    monkeypatch.setattr(ape, "bing_items", lambda rss: [])
    calls = []
    oc.discover(SimpleNamespace(name=None, ticker="ASTS"), lambda url: calls.append(url) or b"<rss/>")
    assert len(calls) == 4 and "ASTS" in calls[0]


def test_default_fetch_delega_en_public_fetch(monkeypatch):
    monkeypatch.setattr(pf, "fetch_public_url", lambda url: (b"<html/>", "text/html", url))
    assert oc._default_fetch("https://x.example.com") == b"<html/>"


def test_robots_allows_sin_robots_y_con_disallow():
    assert (
        oc._robots_allows("https://x.example.com/a", lambda url: (_ for _ in ()).throw(RuntimeError("404")))
        is True
    )
    robots = b"User-agent: *\nDisallow: /news\n"
    assert oc._robots_allows("https://x.example.com/news/a", lambda url: robots) is False
    assert oc._robots_allows("https://x.example.com/ok/a", lambda url: robots) is True


# --- collect ---------------------------------------------------------------------


PRESS_URL = "https://corp.rakuten.co.jp/news/press/2026/1109_02.html"
PRESS_URL_SIN_FECHA = "https://corp.rakuten.co.jp/news/press/release.html"  # sin fecha en la ruta
PRESS_HTML = (
    b"<html><body><h1>Rakuten and AST SpaceMobile Sign Agreement</h1>"
    b"<p>Rakuten Corp today announced a definitive agreement with AST SpaceMobile, Inc. "
    b"on November 9, 2026.</p></body></html>"
)


def _fetch_ok(url):
    if url.endswith("/robots.txt"):
        return b"User-agent: *\nAllow: /\n"
    return PRESS_HTML


def test_collect_prefiltro_sin_descarga_y_dedup():
    company = SimpleNamespace(id=1, name=ASTS.name, ticker="ASTS", ir_url="")
    urls = ["https://www.reuters.com/news/x", "notaurl", "https://www.reuters.com/news/x"]
    report = oc.collect(_DB([[]]), company, 1, urls=urls, fetch=_fetch_ok, discover_news=False)
    assert report["candidates"] == 0 and report["stored"] == [] and report["skipped"] == {}


def test_collect_ya_archivada_no_se_repite():
    company = SimpleNamespace(id=1, name=ASTS.name, ticker="ASTS", ir_url="")
    db = _DB([[PRESS_URL]])  # ya guardada
    report = oc.collect(db, company, 1, urls=[PRESS_URL], fetch=_fetch_ok, discover_news=False)
    assert report["candidates"] == 0 and report["stored"] == []


def test_collect_guarda_documento_con_chunks_y_fecha_de_pagina():
    company = SimpleNamespace(id=1, name=ASTS.name, ticker="ASTS", ir_url="")
    db = _DB([[]])
    report = oc.collect(db, company, 7, urls=[PRESS_URL], fetch=_fetch_ok, discover_news=False)
    assert report["candidates"] == 1 and report["stored"] == [
        {"url": PRESS_URL, "kind": "corporativa", "date": "2026-11-09"}
    ]
    docs = [o for o in db.added if o.__class__.__name__ == "Document"]
    chunks = [o for o in db.added if o.__class__.__name__ == "DocumentChunk"]
    assert len(docs) == 1 and docs[0].tenant_id == 7 and docs[0].metadata_["official"] == "corporativa"
    assert docs[0].metadata_["published_from"] == "página"
    assert docs[0].published_at is not None and len(chunks) == 1 and chunks[0].chunk_index == 0
    assert db.flushed == 1


def test_collect_fecha_del_buscador_si_la_pagina_no_la_tiene():
    html_sin_fecha = (
        b"<html><body><h1>Rakuten and AST SpaceMobile Sign Agreement</h1>"
        b"<p>Rakuten Corp today announced a definitive agreement with AST SpaceMobile, Inc.</p>"
        b"</body></html>"
    )

    def fetch(url):
        if url.endswith("/robots.txt"):
            return b"User-agent: *\nAllow: /\n"
        return html_sin_fecha

    company = SimpleNamespace(id=1, name=ASTS.name, ticker="ASTS", ir_url="")
    db = _DB([[]])
    report = oc.collect(db, company, 1, urls=[PRESS_URL_SIN_FECHA], fetch=fetch, discover_news=False)
    assert report["stored"] == [{"url": PRESS_URL_SIN_FECHA, "kind": "corporativa", "date": None}]
    doc = db.added[0]
    assert doc.published_at is None and doc.metadata_["published_from"] == "buscador"


def test_collect_robots_error_y_pagina_sin_mencion():
    company = SimpleNamespace(id=1, name=ASTS.name, ticker="ASTS", ir_url="")
    url_robots = "https://corp.rakuten.co.jp/news/press/2026/r1.html"
    url_error = "https://corp.rakuten.co.jp/news/press/2026/e2.html"
    url_sin = "https://corp.rakuten.co.jp/news/press/2026/s3.html"

    def fetch(url):
        if "robots.txt" in url:
            return b"User-agent: *\nDisallow: /news/press/2026/r1\n"
        if url.endswith("e2.html"):
            raise ValueError("descarga rota")
        return b"<html><body><p>Rakuten Corp announces an agreement with another company entirely.</p></body></html>"

    db = _DB([[]])
    report = oc.collect(
        db, company, 1, urls=[url_robots, url_error, url_sin], fetch=fetch, discover_news=False
    )
    assert report["candidates"] == 3 and report["stored"] == []
    assert report["skipped"][url_robots] == "robots.txt"
    assert report["skipped"][url_error] == "ValueError"
    assert report["skipped"][url_sin] == "no oficial o no nombra a la empresa"


def test_collect_tope_de_paginas():
    company = SimpleNamespace(id=1, name=ASTS.name, ticker="ASTS", ir_url="")
    urls = [f"https://corp.rakuten.co.jp/news/press/2026/110{i}_0{i}.html" for i in range(3)]
    db = _DB([[]])
    report = oc.collect(db, company, 1, urls=urls, fetch=_fetch_ok, discover_news=False, max_pages=1)
    assert report["candidates"] == 2 and len(report["stored"]) == 1


def test_collect_con_discover_y_newsevent_roto(monkeypatch):
    monkeypatch.setattr(oc, "discover", lambda company, fetch: [(PRESS_URL, "t", date(2026, 11, 9))])
    company = SimpleNamespace(id=1, name=ASTS.name, ticker="ASTS", ir_url="")

    class DBrota(_DB):
        def scalars(self, stmt):
            if not self.rolled_back:
                self.rolled_back = True
                raise RuntimeError("sin news_events")
            return _Rows([])

    db = DBrota()
    report = oc.collect(db, company, 1, fetch=_fetch_ok, discover_news=True)
    assert db.rolled_back is True  # NewsEvent roto no para la recogida
    assert report["candidates"] == 1 and len(report["stored"]) == 1
    assert report["stored"][0]["date"] == "2026-11-09"  # la página la confirma
