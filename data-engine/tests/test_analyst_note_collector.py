"""Recolector de notas de analista: esqueleto Yahoo + noticias ingeridas con LLM
acotado y fail-closed (la cita, la casa y los números tienen que estar en la
noticia). Todo sintético; el LLM es un stub. Sin red."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import AnalystNote
from app.models.entities import Company, NewsEvent, Tenant
from app.services import analyst_note_collector as col
from app.services.analyst_note_collector import (
    collect_for_ticker,
    is_social_url,
    news_evidence,
    numbers_in,
    parse_extraction,
    yahoo_note_inputs,
)

T1, T2 = 1, 2
TODAY = date(2026, 11, 5)
NEWS_URL = "https://news.example.com/barclays-pltr"
HEADLINE = "Barclays maintains Palantir Technologies at Overweight, raises price target to $273 from $265"
SUMMARY = "Barclays analyst Raimo Lenschow said commercial acceleration validates the AIP strategy."


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Tenant(id=T1, external_id="t1"), Tenant(id=T2, external_id="t2")])
        session.add(
            Company(
                id=1,
                ticker="PLTR",
                name="Palantir Technologies",
                exchange="NASDAQ",
                currency="USD",
                company_type="operating",
                valuation_model="standard_dcf",
            )
        )
        session.flush()
        yield session


def _news(db, *, tenant=T1, title=HEADLINE, summary=SUMMARY, url=NEWS_URL, day=date(2026, 11, 4), id_=None):
    row = NewsEvent(
        tenant_id=tenant,
        company_id=1,
        title=title,
        summary=summary,
        url=url,
        source="TradingView",
        date=datetime(day.year, day.month, day.day, 14, tzinfo=UTC),
    )
    if id_ is not None:
        row.id = id_
    db.add(row)
    db.flush()
    return row


YAHOO_RECORDS = [
    {
        "date": datetime(2026, 11, 3),
        "firm": "Barclays",
        "to_grade": "Overweight",
        "from_grade": "Overweight",
        "action": "main",
        "price_target_action": "Raises",
        "price_target": 273.0,
        "prior_target": 265.0,
    },
    {
        "date": datetime(2026, 10, 1),
        "firm": "Morgan Stanley",
        "to_grade": "Equal-Weight",
        "from_grade": "Underweight",
        "action": "up",
        "price_target": 205.0,
        "prior_target": 150.0,
    },
    {
        "date": datetime(2024, 1, 2),
        "firm": "Old Firm",
        "to_grade": "Buy",
        "action": "init",
        "price_target": 20.0,
    },
    {"date": datetime(2026, 10, 2), "firm": None, "action": "up", "price_target": 1.0},
]
CLOSES = [(date(2026, 9, 30), 180.0), (date(2026, 10, 1), 182.5), (date(2026, 11, 3), 207.0)]


def _yahoo(symbol: str) -> dict:
    return {"records": YAHOO_RECORDS, "closes": CLOSES, "currency": "USD", "quote_type": "EQUITY"}


def _stub(answer):
    calls: list[tuple[str, str]] = []

    async def reason(system: str, user: str, max_tokens: int, task: str) -> str:
        calls.append((system, user))
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, str) else json.dumps(answer(json.loads(user)))

    reason.calls = calls  # type: ignore[attr-defined]
    return reason


def _good_note(news: dict, **over) -> dict:
    note = {
        "evidence": news["news"][0]["id"],
        "firm": "Barclays",
        "analyst": "Raimo Lenschow",
        "action": "maintain",
        "rating_old": "Overweight",
        "rating_new": "Overweight",
        "pt_old": 265,
        "pt_new": 273,
        "currency": "USD",
        "key_arguments": ["la aceleración comercial valida la estrategia AIP"],
        "sentiment": "positive",
        "quote": "commercial acceleration validates the AIP strategy",
    }
    note.update(over)
    return {"notes": [note]}


def _collect(db, reasoner=None, *, enabled=True, tenant=T1, fetch=_yahoo):
    return asyncio.run(
        collect_for_ticker(
            db, tenant, "pltr", reasoner=reasoner, enabled=enabled, today=TODAY, yahoo_fetch=fetch
        )
    )


def _rows(db, tenant=T1):
    return list(
        db.scalars(
            select(AnalystNote).where(AnalystNote.tenant_id == tenant).order_by(AnalystNote.note_date.desc())
        )
    )


# --- piezas puras ---------------------------------------------------------


def test_esqueleto_yahoo_mapea_campos_precio_del_dia_y_ventana():
    notes = yahoo_note_inputs("pltr", YAHOO_RECORDS, CLOSES, today=TODAY, currency="USD")
    assert [n.firm for n in notes] == ["Barclays", "Morgan Stanley"]  # sin la vieja ni la sin casa
    barclays, ms = notes
    assert barclays.action == "maintain" and barclays.pt_old == 265.0 and barclays.pt_new == 273.0
    assert barclays.price_at_note == 207.0 and barclays.verification == "fragmento"
    assert barclays.source_type == "yahoo_upgrades_downgrades"
    assert barclays.source_url == "https://finance.yahoo.com/quote/PLTR/analysis/"
    assert barclays.extras == {"yahoo_price_target_action": "Raises"}
    assert ms.action == "upgrade" and ms.rating_old == "Underweight" and ms.price_at_note == 182.5


def test_numeros_del_texto():
    assert numbers_in("PT to $1,268.50 from $265; 45% upside") >= {1268.5, 265.0, 45.0}


def test_redes_y_foros_son_sociales():
    assert is_social_url("https://x.com/someone/status/1")
    assert is_social_url("https://stocktwits.com/news-articles/markets/pltr")
    assert is_social_url("https://old.reddit.com/r/stocks/1")
    assert not is_social_url("https://finance.yahoo.com/news/a")
    assert not is_social_url("https://notx.com/a")


EVIDENCE = [
    {"id": "n-1", "date": "2026-11-04", "source": "TV", "url": NEWS_URL, "text": f"{HEADLINE}\n{SUMMARY}"}
]


@pytest.mark.parametrize(
    ("over", "motivo"),
    [
        ({"quote": "commercial acceleration is accelerating"}, "la cita no aparece"),
        ({"quote": ""}, "la cita no aparece"),
        ({"firm": "Goldman Sachs"}, "la casa no aparece"),
        ({"pt_new": 300}, "números que no están"),
        ({"bull_target": 400}, "números que no están"),
        ({"estimates": {"2027": {"revenue": 9999}}}, "números que no están"),
        ({"evidence": "n-999"}, "no cita una noticia"),
        ({"action": "sell everything"}, "acción no válida"),
    ],
)
def test_extraccion_fail_closed_por_nota(over, motivo):
    parsed = _good_note({"news": EVIDENCE}, **over)
    notes, rejected = parse_extraction(parsed, EVIDENCE, "PLTR")
    assert notes == []
    assert len(rejected) == 1 and motivo in rejected[0]


def test_extraccion_valida_conserva_fuente_y_fecha_de_la_noticia():
    parsed = _good_note({"news": EVIDENCE}, note_date="2020-01-01")
    notes, rejected = parse_extraction(parsed, EVIDENCE, "PLTR")
    assert rejected == [] and len(notes) == 1
    note = notes[0]
    assert note.note_date == date(2026, 11, 4)  # la de la noticia, no la del modelo
    assert note.source_url == NEWS_URL and note.source_type == "news"
    assert note.pt_new == 273.0 and note.extras["evidence"] == "n-1"


def test_json_sin_lista_lanza():
    with pytest.raises(ValueError):
        parse_extraction({"drivers": []}, EVIDENCE, "PLTR")


def test_evidencia_solo_del_tenant_con_senal_de_analista_y_acotada(db, monkeypatch):
    _news(db)
    _news(db, title="Palantir opens a new office in Madrid", summary="Nothing about ratings.")
    _news(db, tenant=T2, title="Jefferies downgrades Palantir to Underperform", url="https://n.example.com/j")
    _news(db, title="Analyst upgrade", url="http://insecure.example.com/x")  # sin https
    _news(db, title="Old analyst note", day=date(2026, 1, 1))  # fuera de ventana
    company = db.get(Company, 1)
    ev = news_evidence(db, T1, company, today=TODAY)
    assert [e["url"] for e in ev] == [NEWS_URL]
    for i in range(5):
        _news(db, title=f"Firm {i} raises price target", url=f"https://n.example.com/{i}")
    assert len(news_evidence(db, T1, company, today=TODAY, limit=3)) == 3


# --- extremo a extremo con BD -----------------------------------------------


def test_yahoo_sin_llm_guarda_esqueletos_idempotente(db):
    reasoner = _stub(RuntimeError("no debe llamarse"))
    first = _collect(db, reasoner, enabled=False)
    assert first.status == "stored" and first.yahoo_status == "ok" and first.news_status == "disabled"
    assert first.stored == 2 and reasoner.calls == []
    rows = _rows(db)
    assert {(r.firm, r.action, r.verification) for r in rows} == {
        ("Barclays", "maintain", "fragmento"),
        ("Morgan Stanley", "upgrade", "fragmento"),
    }
    assert all(r.company_id == 1 for r in rows)
    again = _collect(db, reasoner, enabled=False)
    assert again.stored == 0 and again.unchanged == 2
    assert db.scalar(select(func.count()).select_from(AnalystNote)) == 2


def test_yahoo_caido_no_rompe_ni_guarda(db):
    def boom(symbol):
        raise TimeoutError("yahoo")

    res = _collect(db, enabled=False, fetch=boom)
    assert res.yahoo_status == "unavailable" and res.status == "nothing" and _rows(db) == []


def test_instrumento_que_no_es_accion_no_guarda(db):
    res = _collect(db, enabled=False, fetch=lambda s: {**_yahoo(s), "quote_type": "ETF"})
    assert res.yahoo_status == "not_equity" and _rows(db) == []


def test_noticia_enriquece_el_esqueleto_yahoo_de_la_misma_casa(db):
    _news(db)  # 4-nov; Yahoo lo fecha el 3-nov
    reasoner = _stub(_good_note)
    res = _collect(db, reasoner)
    assert res.news_status == "ok" and res.llm_calls == 1 and res.rejected == []
    barclays = [r for r in _rows(db) if r.firm == "Barclays"]
    assert len(barclays) == 1  # misma fila: fecha y acción del esqueleto
    row = barclays[0]
    assert row.note_date == date(2026, 11, 3) and row.action == "maintain"
    assert row.verification == "verificado" and row.source_type == "news"
    assert row.source_url == NEWS_URL and row.quote == "commercial acceleration validates the AIP strategy"
    assert row.analyst == "Raimo Lenschow" and row.key_arguments
    assert "https://finance.yahoo.com/quote/PLTR/analysis/" in row.links
    assert float(row.price_at_note) == 207.0  # el precio del esqueleto se conserva
    # El LLM solo vio noticias de este tenant y sus textos acotados.
    sent = json.loads(reasoner.calls[0][1])
    assert [n["url"] for n in sent["news"]] == [NEWS_URL]


def test_cita_inventada_no_se_guarda(db):
    _news(db)
    res = _collect(db, _stub(lambda p: _good_note(p, quote="Palantir will double by 2027")))
    assert res.news_status == "ok" and any("la cita no aparece" in r for r in res.rejected)
    assert all(r.verification == "fragmento" and r.quote is None for r in _rows(db))


def test_post_de_red_social_queda_como_rumor(db):
    _news(
        db,
        url="https://stocktwits.com/news-articles/pltr-barclays",
        title="Barclays raises price target on Palantir to $273",
        summary="per a trader post",
    )
    res = _collect(
        db,
        _stub(lambda p: _good_note(p, quote="raises price target on Palantir", pt_old=None)),
        fetch=lambda s: {"records": [], "closes": [], "quote_type": "EQUITY"},
    )
    assert res.yahoo_status == "empty" and res.stored == 1
    (row,) = _rows(db)
    assert row.source_type == "social" and row.verification == "rumor_no_verificado"


def test_json_ilegible_dos_veces_no_guarda_nada_de_noticias(db):
    _news(db)
    reasoner = _stub("esto no es json")
    res = _collect(db, reasoner)
    assert res.news_status == "rejected" and res.llm_calls == 2
    assert "problems_previous_answer" in json.loads(reasoner.calls[1][1])
    assert all(r.verification == "fragmento" for r in _rows(db))


def test_llm_caido_no_guarda_nada_de_noticias(db):
    _news(db)
    res = _collect(db, _stub(RuntimeError("sin presupuesto")))
    assert res.news_status == "error" and res.rejected == ["llm:RuntimeError"]
    assert all(r.verification == "fragmento" for r in _rows(db))


def test_sin_noticias_no_llama_al_llm(db):
    reasoner = _stub(RuntimeError("no debe llamarse"))
    res = _collect(db, reasoner)
    assert res.news_status == "no_news" and reasoner.calls == []


def test_tenant_y_empresa_obligatorios(db):
    assert (
        asyncio.run(collect_for_ticker(db, 0, "PLTR", enabled=False, yahoo_fetch=_yahoo)).status
        == "no_tenant"
    )
    assert (
        asyncio.run(collect_for_ticker(db, T1, "NOPE", enabled=False, yahoo_fetch=_yahoo)).status
        == "no_company"
    )


def test_notas_de_un_tenant_no_las_ve_otro(db):
    _news(db)
    _collect(db, _stub(_good_note))
    assert _rows(db, T2) == []
    _collect(db, _stub(_good_note), tenant=T2)
    # T2 no tiene la noticia: solo esqueletos.
    assert all(r.verification == "fragmento" for r in _rows(db, T2)) and len(_rows(db, T2)) == 2


def test_flag_apagado_por_defecto_no_llama(monkeypatch, db):
    from app.core import config

    class S:
        expert_team_enabled = False

    monkeypatch.setattr(config, "get_settings", lambda: S())
    _news(db)
    reasoner = _stub(RuntimeError("no debe llamarse"))
    res = asyncio.run(collect_for_ticker(db, T1, "PLTR", reasoner=reasoner, today=TODAY, yahoo_fetch=_yahoo))
    assert res.news_status == "disabled" and reasoner.calls == []


def test_limites_declarados():
    assert col.NEWS_MAX_ITEMS <= 25 and col.MAX_ATTEMPTS == 2 and col.FETCH_TIMEOUT_SECONDS <= 30
