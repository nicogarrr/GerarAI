"""Guardia de regresión de rendimiento: consultas SQL por endpoint clave.

Rendimiento-12 (3 nov 2026). Fija lo ganado en las tandas de rendimiento para
que no vuelva un N+1 sin que nadie lo vea. Para cada endpoint clave de las
páginas que más se usan (/inicio, /portfolio, /portfolio/intelligence,
risk-matrix, research/[ticker], watchlist) y para la construcción del
contexto del chat:

1. Se siembran DOS tenants idénticos salvo en el tamaño (``SMALL`` y
   ``LARGE`` posiciones, con su historia de precios, transacciones, FX y
   watchlist). Un endpoint sin N+1 hace las MISMAS consultas con 4 que con 16
   posiciones; si el número crece con la cartera, el test lo dice con las
   sentencias de más.
2. Presupuesto absoluto: el número de sentencias no puede pasar de lo medido
   en main (``BUDGETS``) más un margen pequeño. Si una mejora lo baja,
   el test sigue verde; si se quiere fijar la mejora, se baja el número.
3. Tiempo: presupuesto grueso (``TIME_BUDGET_S``), muy por encima de lo
   medido, para que no dé falsos rojos con la máquina cargada: solo salta si
   algo se vuelve un orden de magnitud más lento.

Herméticos: la DB sqlite de la suite (conftest), tenants y tickers propios
de este fichero, sin red ni LLM (el chat usa un proveedor stub).

Se cuentan TODAS las sentencias que pasan por el engine de la app mientras
dura la petición (``before_cursor_execute``), igual que los bancos de las
tandas de rendimiento (``q=`` en sweep.log).
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

import main
from app.core.auth import ResearchPrincipal, get_research_principal
from app.core.database import SessionLocal, engine, init_db
from app.llm import LLMResponse, Message, Usage
from app.llm.base import LLMProvider
from app.models import (
    Company,
    FinancialFact,
    FXRate,
    MarketPrice,
    Portfolio,
    Position,
    Tenant,
    Transaction,
    WatchItem,
)

SMALL = 4
LARGE = 16
DAYS = 90  # sesiones de precio: >= 60 para que risk-matrix e intelligence calculen


# ---------------------------------------------------------------- contador
class _Counter:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.active = False

    def __call__(self, conn, cursor, statement, parameters, context, executemany):  # noqa: ARG002
        if self.active:
            self.statements.append(statement)


_COUNTER = _Counter()


@contextmanager
def count_queries():
    """Cuenta las sentencias SQL del engine de la app dentro del bloque."""
    _COUNTER.statements = []
    _COUNTER.active = True
    try:
        yield _COUNTER
    finally:
        _COUNTER.active = False


# ---------------------------------------------------------------- semilla
def _price(i: int, k: int) -> float:
    base = 40.0 + 7.0 * k
    return round(base * (1 + 0.0009 + 0.0001 * (k % 5)) ** i + 0.9 * math.sin(i / 3.0 + k), 4)


def _business_days(n: int) -> list[date]:
    out: list[date] = []
    day = date.today()
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day -= timedelta(days=1)
    return list(reversed(out))


def _seed_tenant(n_positions: int) -> dict:
    """Tenant con ``n_positions`` posiciones (mitad USD), precios, FX, transacciones y watchlist."""
    suffix = uuid4().hex[:5].upper()
    external = f"perf-guard-{n_positions}-{suffix.lower()}"
    db = SessionLocal()
    try:
        tenant = Tenant(external_id=external, name=f"Perf guard {n_positions}")
        db.add(tenant)
        db.commit()
        db.info["tenant_id"] = tenant.id
        portfolio = Portfolio(name="Main", base_currency="EUR", is_default=True)
        db.add(portfolio)
        db.flush()
        days = _business_days(DAYS)
        companies: list[Company] = []
        for k in range(n_positions):
            currency = "USD" if k % 2 else "EUR"
            company = Company(
                ticker=f"PG{suffix}{k:02d}",
                name=f"Perf Guard {suffix} {k}",
                exchange="NASDAQ" if currency == "USD" else "XETRA",
                currency=currency,
                sector=["Technology", "Health Care", "Financials", "Energy"][k % 4],
                industry="Software",
                company_type="operating",
                valuation_model="unassigned",
                special_sources=[],
                special_risks=[],
                factor_tags=[],
            )
            db.add(company)
            companies.append(company)
        db.flush()
        for k, company in enumerate(companies):
            for i, day in enumerate(days):
                value = Decimal(str(_price(i, k)))
                db.add(
                    MarketPrice(
                        company_id=company.id,
                        date=day,
                        open=value,
                        high=value,
                        low=value,
                        close=value,
                        adj_close=value,
                        volume=100_000,
                        source="perf-guard",
                    )
                )
        for i, day in enumerate(days):
            db.add(
                FXRate(
                    base_currency="EUR",
                    quote_currency="USD",
                    rate=Decimal("1.08") + Decimal(i % 7) / Decimal(1000),
                    rate_date=day,
                    source="perf-guard",
                )
            )
        for k, company in enumerate(companies):
            qty = Decimal(10 + k)
            buy_price = Decimal(str(_price(0, k)))
            db.add(
                Transaction(
                    portfolio_id=portfolio.id,
                    company_id=company.id,
                    trade_date=days[1],
                    action="buy",
                    quantity=qty + 2,
                    price=buy_price,
                    fees=Decimal("1"),
                    currency=company.currency,
                    external_id=f"pg-{suffix}-{k}-buy",
                    raw_payload={},
                )
            )
            db.add(
                Transaction(
                    portfolio_id=portfolio.id,
                    company_id=company.id,
                    trade_date=days[DAYS // 2],
                    action="sell",
                    quantity=Decimal(2),
                    price=Decimal(str(_price(DAYS // 2, k))),
                    fees=Decimal("1"),
                    currency=company.currency,
                    external_id=f"pg-{suffix}-{k}-sell",
                    raw_payload={},
                )
            )
            db.add(
                Transaction(
                    portfolio_id=portfolio.id,
                    company_id=company.id,
                    trade_date=days[DAYS - 10],
                    action="dividend",
                    quantity=Decimal(0),
                    price=Decimal("3.5"),
                    fees=Decimal("0"),
                    currency=company.currency,
                    external_id=f"pg-{suffix}-{k}-div",
                    raw_payload={},
                )
            )
            last = Decimal(str(_price(DAYS - 1, k)))
            value = (qty * last).quantize(Decimal("0.01"))
            cost = (qty * buy_price).quantize(Decimal("0.01"))
            fx = Decimal("1") if company.currency == "EUR" else Decimal("0.92")
            db.add(
                Position(
                    portfolio_id=portfolio.id,
                    company_id=company.id,
                    quantity=qty,
                    average_cost=buy_price,
                    market_price=last,
                    market_value=value,
                    unrealized_pnl=value - cost,
                    realized_pnl=Decimal("0"),
                    currency=company.currency,
                    base_currency="EUR",
                    fx_rate=fx,
                    market_value_native=value,
                    cost_basis_native=cost,
                    market_value_base=(value * fx).quantize(Decimal("0.01")),
                    cost_basis_base=(cost * fx).quantize(Decimal("0.01")),
                    as_of=days[-1],
                    source="perf-guard",
                )
            )
        # Watchlist: la mitad son posiciones, la otra mitad no.
        for k, company in enumerate(companies):
            if k % 2 == 0:
                db.add(WatchItem(symbol=company.ticker, company=company.name))
        for k in range(n_positions // 2):
            db.add(WatchItem(symbol=f"PW{suffix}{k:02d}", company=f"Watch only {k}"))
        # Research: hechos de la primera empresa, en número proporcional a la cartera.
        lead = companies[0]
        for k in range(n_positions * 2):
            db.add(
                FinancialFact(
                    company_id=lead.id,
                    metric=["revenue", "net_income", "free_cash_flow", "eps"][k % 4],
                    value=Decimal(1000 + k),
                    unit="EUR",
                    period=f"FY{2015 + k // 4}",
                    fiscal_year=2015 + k // 4,
                    source_type="seed",
                )
            )
        db.commit()
        return {
            "external": external,
            "tenant_id": tenant.id,
            "tickers": [c.ticker for c in companies],
            "lead": lead.ticker,
        }
    finally:
        db.close()


@pytest.fixture(scope="module")
def perf_world():
    init_db()
    event.listen(engine, "before_cursor_execute", _COUNTER)
    previous = main.app.dependency_overrides.get(get_research_principal)
    state: dict = {"principal": None}
    main.app.dependency_overrides[get_research_principal] = lambda: state["principal"]
    world = {
        "small": _seed_tenant(SMALL),
        "large": _seed_tenant(LARGE),
        "client": TestClient(main.app, raise_server_exceptions=False),
        "state": state,
    }
    try:
        yield world
    finally:
        event.remove(engine, "before_cursor_execute", _COUNTER)
        if previous is None:
            main.app.dependency_overrides.pop(get_research_principal, None)
        else:
            main.app.dependency_overrides[get_research_principal] = previous


def _get(world, size: str, path: str):
    tenant = world[size]
    world["state"]["principal"] = ResearchPrincipal(
        user_id="perf-guard", tenant_external_id=tenant["external"]
    )
    url = path.format(lead=tenant["lead"], watch=",".join(tenant["tickers"][::2]))
    with count_queries() as counter:
        started = time.perf_counter()
        res = world["client"].get(url)
        elapsed = time.perf_counter() - started
    return res, list(counter.statements), elapsed


# ------------------------------------------------------------- presupuestos
# Sentencias SQL por petición en frío (primera vez para ese tenant), medidas en
# main 96237665 (3 nov 2026) con esta semilla; IGUALES con 4 y con 16
# posiciones. Bajar un número cuando una mejora lo baje; subirlo exige
# explicar en el PR qué consulta nueva hace falta y por qué no escala.
BUDGETS: dict[str, int] = {
    # /inicio: tarjeta Cartera (posiciones + resumen) y watchlist
    "/api/portfolio/positions?page=1&page_size=200": 7,
    "/api/portfolio/summary": 6,
    "/api/watchlist": 5,
    # /portfolio
    "/api/portfolio/transactions?offset=0&limit=50": 6,
    "/api/portfolio/transactions/page?limit=50&offset=0": 6,
    "/api/portfolio/snapshots?page=1&page_size=200": 7,
    "/api/portfolio/tearsheet": 5,
    "/api/portfolio/forecast": 6,
    "/api/portfolio/dividends": 5,
    "/api/portfolio/dividends/projection": 7,
    "/api/portfolio/data-quality": 7,
    "/api/risk/dashboard": 6,
    # /portfolio/intelligence y riesgo
    "/api/portfolio/intelligence": 25,
    "/api/portfolio/risk-matrix": 7,
    # /watchlist
    "/api/watchlist/dca-signals": 10,
    "/api/watchlist/attention-thesis": 4,
    "/api/watchlist/monitor?tickers={watch}": 11,
    # /research/[ticker]
    "/api/companies/{lead}/snapshot": 10,
    "/api/companies/{lead}/facts?limit=250": 5,
    "/api/companies/{lead}/metrics/calculated": 5,
    "/api/companies/{lead}/ttm": 6,
    "/api/valuation/{lead}": 51,
    "/api/companies/{lead}/peers/comparison": 16,
    "/api/companies/{lead}/decision-journal": 5,
    "/api/memory/thesis/{lead}/changes?limit=100": 5,
    "/api/alerts?ticker={lead}&include_snoozed=true": 5,
    "/api/reviews?ticker={lead}": 5,
}

# Construcción del contexto del chat (ChatService.answer con proveedor stub):
# consultas por pregunta, iguales con 4 y con 16 posiciones.
CHAT_BUDGETS: dict[str, int] = {
    "¿Cómo va mi cartera?": 6,
    "¿Cuánto tengo invertido?": 3,
    "¿Cuál es mi mayor posición?": 5,
    "¿Qué tal va mi {lead}?": 2,
    "¿Qué opinas de {lead}?": 18,
    "Analiza mi cartera": 6,
    "¿Qué riesgos ves en mi cartera?": 10,
    "¿Debería diversificar más?": 8,
    "Resume la tesis de {lead}": 18,
}

# Tiempo: gruesos a propósito. Lo medido con esta semilla es 2–40 ms en
# caliente; la primera petición del proceso paga importaciones perezosas (~1 s).
WARM_TIME_BUDGET_S = 2.0
COLD_TIME_BUDGET_S = 10.0


def _allowed(budget: int) -> int:
    """Presupuesto + margen pequeño (20 %, mínimo 2) para no frenar un cambio legítimo."""
    return budget + max(2, budget // 5)


_PARAM_LIST = re.compile(r"\(\s*(?:\?|%\(\w+\)s|:\w+)(?:\s*,\s*(?:\?|%\(\w+\)s|:\w+))*\s*\)")


def _shape(statement: str) -> str:
    """Forma de la sentencia: tabla + WHERE, con las listas IN (?, ?, …) plegadas."""
    text = _PARAM_LIST.sub("(…)", " ".join(statement.split()))
    if " FROM " in text:
        return text.split(" FROM ", 1)[1][:90]
    return text[:90]


def _growth(small: list[str], large: list[str]) -> str:
    from collections import Counter

    a, b = Counter(map(_shape, small)), Counter(map(_shape, large))
    extra = {k: (a.get(k, 0), v) for k, v in b.items() if a.get(k, 0) != v}
    return "; ".join(f"{k} ({s}→{l})" for k, (s, l) in sorted(extra.items(), key=lambda kv: -kv[1][1])[:6])


@pytest.fixture(scope="module")
def endpoint_runs(perf_world):
    """Mide TODOS los endpoints en orden fijo, una vez: el resultado no depende de -k ni del orden."""
    runs = {}
    for path in BUDGETS:
        res_l, stmts_l, cold_l = _get(perf_world, "large", path)
        res_s, stmts_s, cold_s = _get(perf_world, "small", path)
        res_w, _, warm = _get(perf_world, "large", path)
        runs[path] = {
            "large": res_l,
            "small": res_s,
            "warm": res_w,
            "stmts_large": stmts_l,
            "stmts_small": stmts_s,
            "cold_s": max(cold_l, cold_s),
            "warm_s": warm,
        }
    return runs


@pytest.mark.parametrize("path", list(BUDGETS))
def test_consultas_por_endpoint_no_crecen_con_la_cartera(endpoint_runs, path):
    run = endpoint_runs[path]
    for key in ("large", "small", "warm"):
        assert run[key].status_code == 200, f"{path} ({key}) → {run[key].status_code}: {run[key].text[:300]}"
    small, large = run["stmts_small"], run["stmts_large"]
    assert len(large) == len(small), (
        f"N+1 en {path}: {len(small)} consultas con {SMALL} posiciones y {len(large)} con {LARGE}. "
        f"Crecen: {_growth(small, large)}"
    )
    budget = BUDGETS[path]
    assert len(large) <= _allowed(budget), (
        f"{path} hace {len(large)} consultas (presupuesto {budget}, máximo {_allowed(budget)}). "
        f"Si es a propósito, sube BUDGETS y explica la consulta nueva en el PR."
    )


@pytest.mark.parametrize("path", list(BUDGETS))
def test_tiempo_por_endpoint(endpoint_runs, path):
    run = endpoint_runs[path]
    assert run["warm_s"] < WARM_TIME_BUDGET_S, (
        f"{path}: {run['warm_s']:.2f} s en caliente (> {WARM_TIME_BUDGET_S} s)"
    )
    assert run["cold_s"] < COLD_TIME_BUDGET_S, (
        f"{path}: {run['cold_s']:.2f} s en frío (> {COLD_TIME_BUDGET_S} s)"
    )


def test_la_semilla_llega_a_las_respuestas(endpoint_runs):
    """Sin esto, «mismas consultas» podría ser «mismas respuestas vacías»."""
    for size, n in (("small", SMALL), ("large", LARGE)):
        positions = endpoint_runs["/api/portfolio/positions?page=1&page_size=200"][size].json()
        assert len(positions["items"]) == n
        watchlist = endpoint_runs["/api/watchlist"][size].json()
        assert len(watchlist) == n  # n/2 en cartera + n/2 solo vigiladas
        matrix = endpoint_runs["/api/portfolio/risk-matrix"][size].json()
        assert matrix["status"] == "ok"
        assert len([p for p in matrix["positions"] if p["included"]]) == n
        intel = endpoint_runs["/api/portfolio/intelligence"][size].json()
        assert intel["coverage"]["positions"] == n
        facts = endpoint_runs["/api/companies/{lead}/facts?limit=250"][size].json()
        assert len(facts) == 2 * n
        txs = endpoint_runs["/api/portfolio/transactions/page?limit=50&offset=0"][size].json()
        assert len(txs["items"]) == 2 * n  # compras y ventas (los dividendos van aparte)


# --------------------------------------------------------------------- chat
class _StubProvider:
    name = "stub"

    def __init__(self) -> None:
        self.requests: list = []

    async def complete(self, request):
        self.requests.append(request)
        return LLMResponse(
            message=Message("assistant", "Respuesta de prueba."),
            usage=Usage(input_tokens=10, output_tokens=5, total_tokens=15),
            model="stub-model",
            provider="stub",
            request_id="req-perf-guard",
        )


def _chat(world, size: str, question: str):
    from app.services.chat_service import ChatService

    tenant = world[size]
    db = SessionLocal()
    db.info["tenant_id"] = tenant["tenant_id"]
    try:
        with count_queries() as counter:
            started = time.perf_counter()
            resp = asyncio.run(
                ChatService(provider=cast(LLMProvider, _StubProvider())).answer(
                    db, question.format(lead=tenant["lead"]), "portfolio", None
                )
            )
            elapsed = time.perf_counter() - started
    finally:
        db.close()
    return resp, list(counter.statements), elapsed


@pytest.fixture(scope="module")
def chat_runs(perf_world):
    runs = {}
    for question in CHAT_BUDGETS:
        resp_l, stmts_l, t_l = _chat(perf_world, "large", question)
        resp_s, stmts_s, t_s = _chat(perf_world, "small", question)
        _, _, warm = _chat(perf_world, "large", question)
        runs[question] = {
            "large": resp_l,
            "small": resp_s,
            "stmts_large": stmts_l,
            "stmts_small": stmts_s,
            "cold_s": max(t_l, t_s),
            "warm_s": warm,
        }
    return runs


@pytest.mark.parametrize("question", list(CHAT_BUDGETS))
def test_contexto_del_chat_no_crece_con_la_cartera(chat_runs, question):
    run = chat_runs[question]
    assert run["large"].answer and run["small"].answer
    small, large = run["stmts_small"], run["stmts_large"]
    assert len(large) == len(small), (
        f"N+1 en el chat «{question}»: {len(small)} consultas con {SMALL} posiciones y {len(large)} con {LARGE}. "
        f"Crecen: {_growth(small, large)}"
    )
    budget = CHAT_BUDGETS[question]
    assert len(large) <= _allowed(budget), (
        f"chat «{question}» hace {len(large)} consultas (presupuesto {budget}, máximo {_allowed(budget)})"
    )
    assert run["warm_s"] < WARM_TIME_BUDGET_S
    assert run["cold_s"] < COLD_TIME_BUDGET_S


# ------------------------------------------------------- el guardia funciona
def test_el_contador_ve_un_n_mas_1(perf_world):
    """Un bucle con una consulta por posición TIENE que salir como crecimiento."""

    def n_plus_one(size: str) -> int:
        db = SessionLocal()
        db.info["tenant_id"] = perf_world[size]["tenant_id"]
        try:
            with count_queries() as counter:
                for position in db.query(Position).all():
                    db.query(MarketPrice).filter(MarketPrice.company_id == position.company_id).first()
            return len(counter.statements)
        finally:
            db.close()

    assert n_plus_one("large") - n_plus_one("small") == LARGE - SMALL
