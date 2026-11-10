"""Orquestación de prensa hermética: marcas temporales, URLs y fallos de lectura."""

import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.services import analyst_press_estimates as svc

TODAY = date(2026, 11, 9)
CO = SimpleNamespace(id=1, ticker="TEST", name="Test Inc.", currency="USD")


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _DB:
    def __init__(self, *results):
        self.results = iter(results)
        self.statements = []

    def scalars(self, statement):
        self.statements.append(statement)
        return _Rows(next(self.results))


@pytest.mark.parametrize(
    "rows,stale",
    [
        ([], True),
        ([None, "bad", {}], True),
        ([{"kind": "other", "collected_on": "2026-11-09"}], True),
        ([{"kind": "analyst_press", "collected_on": None}], True),
        ([{"kind": "analyst_press", "collected_on": "2026-11-05"}], True),
        ([{"kind": "analyst_press", "collected_on": "2026-11-06"}], False),
        (
            [
                {"kind": "analyst_press", "collected_on": "2026-11-05"},
                {"kind": "analyst_press", "collected_on": "2026-11-09"},
            ],
            False,
        ),
    ],
)
def test_marcas_de_recogida_y_frontera_tres_dias(rows, stale):
    assert svc.press_estimates_stale(_DB(rows), CO, 1, today=TODAY) is stale


def test_refresh_filtra_urls_y_transfiere_parametros(monkeypatch):
    def news(url, title="analyst", summary=None, day=None):
        return SimpleNamespace(url=url, title=title, summary=summary, date=day)

    db = _DB(
        ["Roth", None, "Roth", "UBS"],
        [
            news("https://example.test/a", summary="s", day=datetime(2026, 11, 8, tzinfo=UTC)),
            news("http://example.test/no"),
            news("https://news.google.com/rss/articles/x"),
            news("  https://example.test/b  "),
            news(""),
        ],
    )
    reading = svc.ArticleReading()
    article = svc.Article("https://example.test/a", "t", TODAY, "text")
    calls = []
    fetch = object()

    async def collect(company, **kw):
        calls.append((company, kw))
        return svc.CollectReport(
            articles_seen=5,
            articles_read=2,
            skipped_robots=["b", "a", "b"],
            failed=[str(i) for i in range(25)],
            readings=[(article, reading)],
        )

    def store(db_arg, company, tenant, readings):
        assert db_arg is db and company is CO and tenant == 1
        assert readings == [(article, reading)]
        return {"stored": ["item"], "skipped": ["reason"]}

    monkeypatch.setattr(svc, "collect", collect)
    monkeypatch.setattr(svc, "store_readings", store)
    out = svc.refresh_press_estimates(db, CO, 1, today=TODAY, fetch=fetch, max_articles=8)
    assert out == {
        "articles_seen": 5,
        "articles_read": 2,
        "with_estimates": 1,
        "skipped_robots": ["a", "b"],
        "failed": [str(i) for i in range(20)],
        "stored": ["item"],
        "skipped": ["reason"],
    }
    assert calls == [
        (
            CO,
            {
                "known_urls": [
                    ("https://example.test/a", "analyst s", date(2026, 11, 8)),
                    ("https://example.test/b", "analyst ", None),
                ],
                "extra_firms": ["Roth", "UBS"],
                "max_articles": 8,
                "fetch": fetch,
                "today": TODAY,
            },
        )
    ]
    assert len(db.statements) == 2


def test_collect_documentos_validos_vacios_y_errores(monkeypatch):
    monkeypatch.setattr(svc, "MIN_INTERVAL_S", 0)
    urls = [f"https://example.test/{i}" for i in range(4)]
    fetched = []

    async def fetch(url):
        fetched.append(url)
        if "bing.com" in url:
            raise RuntimeError("search unavailable")
        if url.endswith("/robots.txt"):
            return b"User-agent: *\nAllow: /", {}, url
        if url == urls[0]:
            raise ValueError("unreadable")
        if url == urls[1]:
            return b"", {}, url
        if url == urls[2]:
            return (
                b"<article><p>Clear Street expects Test revenue of $100 million in 2027.</p></article>",
                {},
                url,
            )
        return (
            b"<article><p>This is a long enough article without estimates or an analyst at all.</p></article>",
            {},
            url,
        )

    known = [(url, "analyst forecast", TODAY) for url in urls]
    known += [
        (urls[2] + "#duplicate", "analyst forecast", TODAY),
        ("https://example.test/old", "analyst", date(2020, 1, 1)),
        ("https://example.test/unrelated", "ordinary product launch", TODAY),
    ]
    report = asyncio.run(svc.collect(CO, known_urls=known, today=TODAY, fetch=fetch))
    assert report.articles_seen == 4 and report.articles_read == 2
    assert len(report.readings) == 1
    assert report.readings[0][1].estimates[0].amount == 100_000_000
    assert report.failed == ["bing: RuntimeError", "bing: RuntimeError", "example.test: ValueError"]
    assert not any("old" in url or "unrelated" in url or "#duplicate" in url for url in fetched)
    assert fetched.count("https://example.test/robots.txt") == 1
