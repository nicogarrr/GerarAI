"""FinnhubProfileBackfill contract tests (PR-D resto).

The backfill must stay inside the free-tier rate budget (bounded companies
per run), write only what the API returns (a quote-dated market cap, never
an ingest-dated one), leave good Company fields untouched, and resume from
the per-company finnhub_profile Document instead of re-burning budget.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Document, FinancialFact
from app.services.finnhub_profile_backfill import FinnhubProfileBackfill


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class _Resp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data


class _Client:
    """Stub httpx.Client: payload por (fragmento de URL, ticker)."""

    def __init__(self, quotes=None, profiles=None):
        self.quotes = quotes or {}
        self.profiles = profiles or {}
        self.calls = []

    def get(self, url, params=None):
        ticker = (params or {}).get("symbol", "")
        self.calls.append(url)
        if "/quote" in url:
            data = self.quotes.get(ticker)
        else:
            data = self.profiles.get(ticker)
        return _Resp(data or {})

    def close(self):
        pass


class _FakePacer:
    """Pacer compartido de banco: cuenta huecos y cooldowns, sin sleeps."""

    def __init__(self, blocked: float = 0.0):
        self.waits = 0
        self.cooldowns: list[float] = []
        self._blocked = blocked

    def wait_sync(self) -> None:
        self.waits += 1

    def cool_down(self, seconds: float) -> None:
        self.cooldowns.append(seconds)
        self._blocked = max(self._blocked, seconds)

    def blocked_for(self) -> float:
        return self._blocked


class _Settings:
    finnhub_api_key = "test-key"


class _NoKey:
    finnhub_api_key = None


def _company(db: Session, ticker: str, **overrides) -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="UNKNOWN", currency="USD",
        sector="", industry="", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    for key, value in overrides.items():
        setattr(company, key, value)
    db.add(company)
    db.commit()
    return company


def test_backfill_fills_profile_and_quote_dated_market_cap(db):
    company = _company(db, "XYZ", exchange="NASDAQ")
    client = _Client(
        quotes={"XYZ": {"c": 25.5, "t": int(datetime(2026, 10, 16, 20, 0, tzinfo=UTC).timestamp())}},
        profiles={"XYZ": {
            "name": "Xylem Robotics Inc", "exchange": "NASDAQ NMS - GLOBAL MARKET",
            "currency": "USD", "country": "US", "finnhubIndustry": "Technology",
            "marketCapitalization": 1234.0,
        }},
    )
    service = FinnhubProfileBackfill(settings=_Settings(), client=client, pacer=_FakePacer())
    result = service.backfill(db, today=date(2026, 10, 17))

    assert result["status"] == "ok"
    assert result["procesadas"] == 1
    assert result["market_cap"] == 1
    assert company.name == "Xylem Robotics Inc"
    # exchange conocido no se pisa con el valor del perfil (regla anti-ADR).
    assert company.exchange == "NASDAQ"
    assert company.domicile_country == "US"
    cap = db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "market_cap",
        )
    )
    assert cap is not None
    assert cap.value == Decimal("1234000000")
    assert cap.period == "2026-10-16"  # sesion de la quote, no el dia de ingesta
    assert cap.source_type == "Finnhub"
    assert cap.is_reported is True
    doc = db.scalar(select(Document).where(Document.company_id == company.id))
    assert doc.source_type == "finnhub_profile"
    assert doc.metadata_["quote_date"] == "2026-10-16"
    assert doc.metadata_["market_cap_written"] is True


def test_backfill_never_overwrites_good_fields(db):
    company = _company(db, "ABC", name="Real Name", exchange="NASDAQ", domicile_country="GB")
    client = _Client(
        quotes={"ABC": {"c": 10.0, "t": int(datetime(2026, 10, 16, 20, 0, tzinfo=UTC).timestamp())}},
        profiles={"ABC": {"name": "Otro Nombre", "exchange": "LSE", "country": "US"}},
    )
    service = FinnhubProfileBackfill(settings=_Settings(), client=client, pacer=_FakePacer())
    service.backfill(db, today=date(2026, 10, 17))
    assert company.name == "Real Name"
    assert company.exchange == "NASDAQ"
    assert company.domicile_country == "GB"


def test_placeholder_exchange_promotes_only_name_adr_stays_candidate(db):
    """Objecion de revision: SAN con exchange placeholder -> Finnhub resuelve
    el ADR (NYSE/USD/US); promover identidad o market_cap escribiria OTRO
    instrumento. Solo el nombre se promueve; el resto queda declarado como
    candidato en metadata del Document."""
    company = _company(db, "SAN")  # exchange UNKNOWN por defecto
    client = _Client(
        quotes={"SAN": {"c": 4.9, "t": int(datetime(2026, 10, 16, 20, 0, tzinfo=UTC).timestamp())}},
        profiles={"SAN": {
            "name": "Banco Santander SA", "exchange": "NYSE",
            "currency": "USD", "country": "US",
            "marketCapitalization": 80000.0,
        }},
    )
    service = FinnhubProfileBackfill(settings=_Settings(), client=client, pacer=_FakePacer())
    result = service.backfill(db, today=date(2026, 10, 17))

    assert company.name == "Banco Santander SA"
    assert company.exchange == "UNKNOWN"  # nunca el NYSE del ADR
    assert company.currency == "USD"  # ya era USD; no promovido desde perfil
    assert company.domicile_country in (None, "")
    assert result["market_cap"] == 0
    assert db.scalar(
        select(FinancialFact).where(FinancialFact.company_id == company.id)
    ) is None
    doc = db.scalar(select(Document).where(Document.company_id == company.id))
    candidates = doc.metadata_["adr_candidates"]
    assert candidates["exchange"] == "NYSE"
    assert candidates["country"] == "US"
    assert candidates["market_cap_usd_millions"] == "80000.0"
    assert doc.metadata_["market_cap_written"] is False


def test_backfill_skips_companies_checked_recently(db):
    company = _company(db, "OLD")
    db.add(Document(company_id=company.id, title="Finnhub profile backfill 2026-10-10",
                    source_type="finnhub_profile", metadata_={"date": "2026-10-10"}))
    db.commit()
    client = _Client(profiles={"OLD": {"name": "No deberia consultarse"}})
    service = FinnhubProfileBackfill(settings=_Settings(), client=client, pacer=_FakePacer())
    result = service.backfill(db, today=date(2026, 10, 17))
    assert result["procesadas"] == 0
    assert client.calls == []


def test_backfill_budget_limits_companies_per_run(db):
    for i in range(5):
        _company(db, f"T{i}")
    client = _Client(profiles={f"T{i}": {"name": f"Nombre {i}"} for i in range(5)})
    service = FinnhubProfileBackfill(settings=_Settings(), client=client, pacer=_FakePacer())
    result = service.backfill(db, max_companies=2, today=date(2026, 10, 17))
    assert result["procesadas"] == 2
    assert result["pendientes_tras_run"] == 3
    assert client.calls == [u for t in ("T0", "T1") for u in
                          ("https://finnhub.io/api/v1/quote", "https://finnhub.io/api/v1/stock/profile2")]


def test_backfill_records_empty_answers_and_does_not_invent(db):
    company = _company(db, "NOP")
    client = _Client(quotes={"NOP": {}}, profiles={"NOP": {}})
    service = FinnhubProfileBackfill(settings=_Settings(), client=client, pacer=_FakePacer())
    result = service.backfill(db, today=date(2026, 10, 17))
    assert result["sin_datos"] == 1
    assert db.scalar(select(FinancialFact).where(FinancialFact.company_id == company.id)) is None
    doc = db.scalar(select(Document).where(Document.company_id == company.id))
    assert doc.metadata_["empty"] is True


def test_backfill_without_quote_date_writes_no_market_cap(db):
    company = _company(db, "NOD")
    client = _Client(
        quotes={"NOD": {}},
        profiles={"NOD": {"name": "Sin Fecha SA", "marketCapitalization": 500.0}},
    )
    service = FinnhubProfileBackfill(settings=_Settings(), client=client, pacer=_FakePacer())
    result = service.backfill(db, today=date(2026, 10, 17))
    assert result["market_cap"] == 0
    assert db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric == "market_cap",
        )
    ) is None


def test_backfill_without_api_key_writes_nothing(db):
    _company(db, "KEY")
    service = FinnhubProfileBackfill(settings=_NoKey(), client=_Client(), pacer=_FakePacer())
    result = service.backfill(db, today=date(2026, 10, 17))
    assert result["status"] == "sin_clave"
    assert db.scalar(select(Document)) is None


class _Resp429:
    status_code = 429

    def __init__(self, retry_after=None):
        # httpx.Headers: insensible a mayusculas, como la respuesta real.
        self.headers = httpx.Headers({} if retry_after is None else {"Retry-After": str(retry_after)})

    def json(self):  # pragma: no cover - nunca se llama en un 429
        raise AssertionError("no se parsea el cuerpo de un 429")


class _Client429:
    """Todo 429; cuenta las llamadas que se hacen contra la ventana cerrada."""

    def __init__(self, retry_after=60):
        self.calls = []
        self.retry_after = retry_after

    def get(self, url, params=None):
        self.calls.append(url)
        return _Resp429(self.retry_after)

    def close(self):
        pass


def test_backfill_429_corta_la_corrida_y_propaga_el_cooldown(db):
    """Un 429 no es un fallo de transporte mas: la ventana es del proveedor.

    Antes: 300 empresas x 2 llamadas = 600 peticiones contra la ventana
    cerrada, contadas como "error" de transporte y resultado "ok".
    """
    for i in range(5):
        _company(db, f"R{i}")
    client = _Client429(retry_after=90)
    pacer = _FakePacer()
    service = FinnhubProfileBackfill(settings=_Settings(), client=client, pacer=pacer)
    result = service.backfill(db, today=date(2026, 10, 17))

    assert result["status"] == "partial"
    assert result["reason"] == "finnhub_429"
    assert result["retry_after_seconds"] == 90
    # UNA llamada (la quote de la primera empresa), no 10: el 429 corta antes
    # del profile y antes de las demas empresas.
    assert client.calls == ["https://finnhub.io/api/v1/quote"]
    assert pacer.cooldowns == [90]  # Retry-After del servidor, propagado a todos
    assert result["procesadas"] == 0
    assert result["pendientes_tras_run"] == 5
    # Sin Document de reanudacion: las 5 se retoman en la siguiente pasada.
    assert db.scalar(select(Document)) is None


def test_backfill_429_sin_retry_after_usa_el_suelo_de_60s(db):
    _company(db, "R0")
    pacer = _FakePacer()
    service = FinnhubProfileBackfill(settings=_Settings(), client=_Client429(retry_after=None), pacer=pacer)
    result = service.backfill(db, today=date(2026, 10, 17))

    assert result["reason"] == "finnhub_429"
    assert result["retry_after_seconds"] is None
    assert result["cooldown_seconds"] == 60.0
    assert pacer.cooldowns == [60.0]


def test_backfill_con_cooldown_vigente_no_hace_ninguna_llamada(db):
    """El cooldown lo pudo marcar OTRO carril (precios/valoracion): cero llamadas."""
    _company(db, "R0")
    client = _Client429()
    pacer = _FakePacer(blocked=45.0)
    service = FinnhubProfileBackfill(settings=_Settings(), client=client, pacer=pacer)
    result = service.backfill(db, today=date(2026, 10, 17))

    assert result == {
        "status": "skipped",
        "reason": "finnhub_cooldown_429",
        "blocked_for_seconds": 45,
        "procesadas": 0,
    }
    assert client.calls == []
    assert pacer.waits == 0
    assert db.scalar(select(Document)) is None


def test_backfill_cada_llamada_reserva_su_hueco_en_el_pacer_global(db):
    """El ritmo lo pone el pacer compartido (~50/min agregado), no un sleep propio."""
    for i in range(3):
        _company(db, f"P{i}")
    client = _Client(profiles={f"P{i}": {"name": f"Nombre {i}"} for i in range(3)})
    pacer = _FakePacer()
    service = FinnhubProfileBackfill(settings=_Settings(), client=client, pacer=pacer)
    result = service.backfill(db, today=date(2026, 10, 17))

    assert result["status"] == "ok"
    assert result["procesadas"] == 3
    assert len(client.calls) == 6
    assert pacer.waits == 6  # un hueco por llamada HTTP, nunca por empresa


def test_backfill_429_a_mitad_conserva_lo_procesado_y_lo_pendiente(db):
    """429 en la 3a empresa: las 2 primeras quedan con Document (no se
    repiten manana) y las 3 restantes siguen pendientes."""
    for i in range(5):
        _company(db, f"M{i}")

    class _Client429EnLaTercera:
        def __init__(self):
            self.calls = []

        def get(self, url, params=None):
            empresa = len(self.calls) // 2  # quote+profile por empresa
            self.calls.append(url)
            if empresa < 2:
                if "/quote" in url:
                    return _Resp({"c": 10.0, "t": int(datetime(2026, 10, 16, 20, 0, tzinfo=UTC).timestamp())})
                return _Resp({"name": f"Nombre {empresa}"})
            return _Resp429(60)

        def close(self):
            pass

    client = _Client429EnLaTercera()
    pacer = _FakePacer()
    service = FinnhubProfileBackfill(settings=_Settings(), client=client, pacer=pacer)
    result = service.backfill(db, today=date(2026, 10, 17))

    assert result["status"] == "partial"
    assert result["reason"] == "finnhub_429"
    assert result["procesadas"] == 2
    assert result["pendientes_tras_run"] == 3
    assert len(client.calls) == 5  # 2 empresas completas + 1 quote condenada
    docs = db.scalars(select(Document)).all()
    assert len(docs) == 2  # M0 y M1: su Document de reanudacion ya existe
    assert pacer.cooldowns == [60]


def test_backfill_sin_pacer_inyectado_usa_el_global_compartido(db):
    """El defecto de prod: el singleton del conector (mismo hueco que precios)."""
    from app.services.connectors.finnhub import finnhub_pacer

    service = FinnhubProfileBackfill(settings=_Settings(), client=_Client())
    assert service._pacer is finnhub_pacer()
    service.close()


def test_backfill_error_de_transporte_cuenta_y_no_escribe_document(db):
    """Fallo de red (no 429): error contado, sin Document, se retoma manana."""

    class _ClientRoto:
        def __init__(self):
            self.calls = 0

        def get(self, url, params=None):
            self.calls += 1
            raise httpx.ConnectError("caida de red")

        def close(self):
            pass

    _company(db, "NET")
    client = _ClientRoto()
    pacer = _FakePacer()
    service = FinnhubProfileBackfill(settings=_Settings(), client=client, pacer=pacer)
    result = service.backfill(db, today=date(2026, 10, 17))

    assert result["status"] == "ok"
    assert result["error"] == 1
    assert result["procesadas"] == 1
    assert client.calls == 2  # quote + profile, ambas fallan
    assert pacer.cooldowns == []  # un fallo de red no cierra la ventana de nadie
    assert db.scalar(select(Document)) is None


def test_backfill_market_cap_dedup_en_lote_sin_duplicar(db):
    """El dedup de market_cap se hace en UNA consulta por corrida (set en
    memoria) y sigue sin duplicar: un hecho ya escrito para la misma sesion
    no se reinserta, y el de OTRA fuente/periodo no bloquea."""
    from sqlalchemy import func

    quote = {"c": 25.5, "t": int(datetime(2026, 10, 16, 20, 0, tzinfo=UTC).timestamp())}
    profile = {
        "name": "Real", "exchange": "NASDAQ NMS - GLOBAL MARKET", "currency": "USD",
        "country": "US", "finnhubIndustry": "Technology", "marketCapitalization": 1234.0,
    }
    dup = _company(db, "DUP", exchange="NASDAQ")
    new = _company(db, "NEW", exchange="NASDAQ")
    # Hecho existente de la MISMA sesion para DUP: no se debe duplicar.
    db.add(FinancialFact(
        company_id=dup.id, metric="market_cap", value=Decimal("1"), unit="USD",
        period="2026-10-16", source_id=None, source_type="Finnhub",
        is_reported=True, confidence=Decimal("0.75"),
    ))
    # Hecho de OTRA fuente para NEW, mismo periodo: NO bloquea el de Finnhub.
    db.add(FinancialFact(
        company_id=new.id, metric="market_cap", value=Decimal("2"), unit="USD",
        period="2026-10-16", source_id=None, source_type="Manual",
        is_reported=True, confidence=Decimal("1"),
    ))
    db.commit()
    client = _Client(quotes={"DUP": quote, "NEW": quote}, profiles={"DUP": profile, "NEW": profile})
    result = FinnhubProfileBackfill(settings=_Settings(), client=client, pacer=_FakePacer()).backfill(
        db, today=date(2026, 10, 17))
    assert result["market_cap"] == 1  # solo NEW
    rows = db.scalars(
        select(FinancialFact).where(
            FinancialFact.metric == "market_cap",
            FinancialFact.source_type == "Finnhub",
        )
    ).all()
    assert len(rows) == 2  # el preexistente de DUP + el nuevo de NEW
    assert {r.company_id for r in rows} == {dup.id, new.id}
    n_dup = db.scalar(select(func.count(FinancialFact.id)).where(
        FinancialFact.company_id == dup.id, FinancialFact.source_type == "Finnhub"))
    assert n_dup == 1  # sin duplicado
