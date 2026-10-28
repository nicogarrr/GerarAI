"""IBKR Flex, E2E de release con Flex SIMULADO (P0-4).

Recorre el camino completo sin red ni credenciales reales:

    token Flex -> SendRequest/GetStatement (httpx MockTransport) -> compuerta de
    informe -> importador -> libro (Transaction) / posiciones / caja -> diario
    (enlace sugerido) -> actor del scheduler diario por tenant.

Todo es determinista: fecha congelada (2026-10-27), fixtures XML anonimos en
``tests/fixtures/ibkr_flex/`` (cuenta U0000001, emisores ficticios ACME y BETA),
ningun socket saliente (se bloquea ``socket.connect``) y token sintetico.

Lo que NO prueba (ver docs/ibkr/e2e-release.md): formato real de una cuenta
IBKR, latencia real, limites de Vercel, IP allow-list ni el token real.

Run from data-engine/:
    pytest tests/test_ibkr_release_e2e.py -v
"""

from __future__ import annotations

import asyncio
import logging
import socket
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text

from app.core.config import Settings
from app.core.database import SessionLocal, init_db
from app.core.llm_settings_crypto import decrypt_api_key
from app.models import (
    CashBalance,
    Company,
    DecisionJournalEntry,
    IBKRConnection,
    Position,
    Tenant,
    Transaction,
)
from app.services import ibkr_connection_service as service
from app.services import ibkr_import_service as import_module
from app.services.connectors import ibkr as flex_module
from app.workers import dramatiq_app as workers

FIXTURES = Path(__file__).parent / "fixtures" / "ibkr_flex"
TODAY = date(2026, 10, 27)
TOKEN = "7771234567890123"  # sintetico, solo digitos como exige la validacion
OTHER_TOKEN = "8884567890123456"
QUERY_ID = "424242"
ACCOUNT = "U0000001"
KEY = "0123456789abcdef0123456789abcdef"
REF = "9900001111"

PENDING = (
    "<FlexStatementResponse><Status>Warn</Status><ErrorCode>1019</ErrorCode>"
    "<ErrorMessage>Statement generation in progress</ErrorMessage></FlexStatementResponse>"
)
EXPIRED = (
    "<FlexStatementResponse><Status>Fail</Status><ErrorCode>1012</ErrorCode>"
    "<ErrorMessage>Token has expired</ErrorMessage></FlexStatementResponse>"
)
SEND_OK = (
    "<FlexStatementResponse><Status>Success</Status>"
    f"<ReferenceCode>{REF}</ReferenceCode></FlexStatementResponse>"
)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FrozenDate(date):
    @classmethod
    def today(cls):  # noqa: D401
        return cls(TODAY.year, TODAY.month, TODAY.day)


class FakeFlex:
    """Servidor Flex falso: SendRequest -> ReferenceCode, GetStatement -> extracto."""

    def __init__(self) -> None:
        self.statement = fixture("day1_initial.xml")
        self.send_response = SEND_OK
        self.get_responses: list[str] = []  # se consumen antes del extracto
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("SendRequest"):
            return httpx.Response(200, text=self.send_response)
        if request.url.path.endswith("GetStatement"):
            if self.get_responses:
                return httpx.Response(200, text=self.get_responses.pop(0))
            return httpx.Response(200, text=self.statement)
        return httpx.Response(404, text="unexpected")

    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]


@pytest.fixture(autouse=True)
def hermetic(monkeypatch):
    """Fecha congelada, sin sockets salientes, sin cola de precios, clave de cifrado explicita."""
    monkeypatch.setattr(import_module, "date", FrozenDate)
    monkeypatch.setattr(service, "date", FrozenDate)

    def no_network(*args, **kwargs):
        raise AssertionError("el E2E de IBKR no puede abrir sockets reales")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    import app.services.market_close_sync as price_sync

    monkeypatch.setattr(price_sync, "enqueue_price_backfills", lambda *a, **k: 0)
    monkeypatch.setattr(flex_module.IBKRFlexClient, "poll_delay_seconds", 0)
    settings = Settings(_env_file=None, app_env="test", llm_settings_encryption_key=KEY)
    monkeypatch.setattr(workers, "get_settings", lambda: settings)
    init_db()
    return settings


@pytest.fixture
def flex(monkeypatch):
    fake = FakeFlex()
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        flex_module.httpx, "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(fake.handler), **kwargs),
    )
    return fake


@pytest.fixture
def settings(hermetic):
    return hermetic


def make_tenant(user_id: str | None = None) -> tuple[int, str]:
    user_id = user_id or f"user-{uuid4().hex[:8]}"
    with SessionLocal() as db:
        row = Tenant(external_id=uuid4().hex, name="synthetic", metadata_={"created_by": user_id})
        db.add(row)
        db.commit()
        return row.id, user_id


def scoped(tenant_id: int):
    db = SessionLocal()
    db.info["tenant_id"] = tenant_id
    db.info["user_id"] = "e2e"
    return db


def connect(tenant_id: int, settings: Settings, *, complete_query: bool = True, token: str = TOKEN) -> dict:
    """Alta como la ruta de Ajustes: descargar, validar el informe y guardar cifrado."""
    with scoped(tenant_id) as db:
        xml = asyncio.run(service.download(token, QUERY_ID))
        report_date = service.check_report(xml, ACCOUNT)
        return service.save_connection(
            db, settings, token=token, query_id=QUERY_ID, account_id=ACCOUNT,
            complete_query=complete_query, statement_date=report_date,
        )


def sync(tenant_id: int, user_id: str) -> dict:
    return workers.sync_one_tenant_ibkr.fn(tenant_id, user_id)


def trades(db, ticker: str, action: str | None = None) -> list[Transaction]:
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    query = select(Transaction).where(Transaction.company_id == company.id)
    if action:
        query = query.where(Transaction.action == action)
    return list(db.scalars(query.order_by(Transaction.external_id)).all())


def position(db, ticker: str) -> Position | None:
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    return db.scalar(select(Position).where(Position.company_id == company.id))


def net_ledger_quantity(db, ticker: str) -> Decimal:
    buys = sum((t.quantity for t in trades(db, ticker, "buy")), Decimal("0"))
    sells = sum((t.quantity for t in trades(db, ticker, "sell")), Decimal("0"))
    return buys - sells


# --------------------------------------------------------------------------- #
# Dia 1: Flex -> ledger -> posiciones y caja
# --------------------------------------------------------------------------- #

def test_day1_flex_to_ledger_positions_cash_and_dividend_money(flex, settings):
    tenant_id, user_id = make_tenant()
    connect(tenant_id, settings)
    result = sync(tenant_id, user_id)
    assert result["status"] == "synced"
    assert result["connected"] is True and result["complete_query"] is True
    assert result["statement_date"] == date(2026, 10, 26)

    with scoped(tenant_id) as db:
        acme = trades(db, "ACME", "buy")
        assert [(t.external_id, t.quantity, t.price, t.fees, t.currency) for t in acme] == [
            ("T-1001", Decimal("100"), Decimal("10.00"), Decimal("1.00"), "USD")
        ]
        beta = trades(db, "BETA", "buy")
        assert [(t.quantity, t.price, t.currency) for t in beta] == [(Decimal("50"), Decimal("20.00"), "EUR")]
        # Dinero: dividendo bruto, retencion (negativa) y comision quedan con su tipo,
        # no mezclados ni descartados (el informe fiscal los lee por action).
        cash_rows = {t.external_id: (t.action, t.price) for t in db.scalars(select(Transaction).where(Transaction.external_id.like("C-%")))}
        assert cash_rows == {
            "C-2001": ("dividend", Decimal("12.50")),
            "C-2002": ("withholding", Decimal("-1.88")),
            "C-2003": ("fee", Decimal("-0.50")),
        }
        # Libro y posicion cuadran: cantidad neta del libro == posicion del extracto.
        for ticker, expected in (("ACME", Decimal("100")), ("BETA", Decimal("50"))):
            assert net_ledger_quantity(db, ticker) == expected
            assert position(db, ticker).quantity == expected
        pos = position(db, "ACME")
        assert (pos.average_cost, pos.market_price, pos.source) == (Decimal("10.01"), Decimal("10.50"), "ibkr_flex")
        cash = {c.currency: (c.balance, c.settled_cash, c.source) for c in db.scalars(select(CashBalance))}
        assert cash == {
            "USD": (Decimal("8948.50"), Decimal("8948.50"), "ibkr_flex"),
            "EUR": (Decimal("999.00"), Decimal("999.00"), "ibkr_flex"),
        }


def test_flex_protocol_polls_until_ready_and_sends_token_only_in_the_query(flex, settings, caplog):
    caplog.set_level(logging.DEBUG)
    flex.get_responses = [PENDING, PENDING]
    tenant_id, user_id = make_tenant()
    connect(tenant_id, settings)
    sync(tenant_id, user_id)
    sends = [r for r in flex.requests if r.url.path.endswith("SendRequest")]
    gets = [r for r in flex.requests if r.url.path.endswith("GetStatement")]
    # alta (2 intentos pendientes + 1 listo) y sync (1): el cliente reintenta 1019.
    assert len(sends) == 2 and len(gets) == 4
    assert all(r.method == "GET" for r in flex.requests)
    assert all(r.url.params["t"] == TOKEN and r.url.params["v"] == "3" for r in flex.requests)
    assert all(r.url.params["q"] == QUERY_ID for r in sends)
    assert all(r.url.params["q"] == REF for r in gets)  # el GetStatement usa el ReferenceCode
    assert all(r.url.host == "ndcdyn.interactivebrokers.com" for r in flex.requests)
    assert TOKEN not in caplog.text


# --------------------------------------------------------------------------- #
# Dia 2: solape de extractos, parciales, idempotencia, reconcile
# --------------------------------------------------------------------------- #

def test_overlapping_statement_with_partial_fills_is_idempotent_and_reconciles(flex, settings):
    tenant_id, user_id = make_tenant()
    connect(tenant_id, settings)
    sync(tenant_id, user_id)

    flex.statement = fixture("day2_partials.xml")
    result = sync(tenant_id, user_id)
    assert result["status"] == "synced" and result["statement_date"] == TODAY

    def snapshot():
        with scoped(tenant_id) as db:
            return (
                db.scalar(text("select count(*) from transactions where tenant_id = :t"), {"t": tenant_id}),
                sorted((t.external_id, t.action, t.quantity, t.price, t.fees) for t in db.scalars(select(Transaction))),
            )

    count_after_day2, rows_after_day2 = snapshot()
    # 2 compras dia 1 + 3 ventas dia 2 + 3 caja (T-1001/1002 y C-200x reenviados NO duplican).
    assert count_after_day2 == 8
    with scoped(tenant_id) as db:
        sells = trades(db, "ACME", "sell")
        # Dos ejecuciones parciales de la misma orden O-3: ambas, con cantidad POSITIVA
        # aunque Flex las envie negativas, y comision en valor absoluto.
        assert [(t.external_id, t.quantity, t.price, t.fees) for t in sells] == [
            ("T-1003", Decimal("40"), Decimal("11.00"), Decimal("0.40")),
            ("T-1004", Decimal("20"), Decimal("11.10"), Decimal("0.20")),
        ]
        assert {t.raw_payload["ibOrderID"] for t in sells} == {"O-3"}
        assert net_ledger_quantity(db, "ACME") == Decimal("40") == position(db, "ACME").quantity
        # BETA se vendio entera y el extracto completo ya no la trae: se cierra la posicion.
        assert net_ledger_quantity(db, "BETA") == Decimal("0")
        assert position(db, "BETA") is None
        assert {c.currency: c.balance for c in db.scalars(select(CashBalance))} == {
            "USD": Decimal("9606.90"), "EUR": Decimal("2017.00"),
        }

    # Re-sincronizar el MISMO extracto no cambia nada (idempotencia total).
    sync(tenant_id, user_id)
    assert snapshot() == (count_after_day2, rows_after_day2)


def test_merge_mode_without_complete_query_never_closes_positions(flex, settings):
    tenant_id, user_id = make_tenant()
    connect(tenant_id, settings, complete_query=False)
    sync(tenant_id, user_id)
    flex.statement = fixture("day2_partials.xml")
    result = sync(tenant_id, user_id)
    assert result["status"] == "partial"
    assert "sin cerrar posiciones ausentes" in result["message"]
    with scoped(tenant_id) as db:
        # Consulta no declarada completa: BETA ya no viene pero NO se borra.
        assert position(db, "BETA").quantity == Decimal("50")
        assert position(db, "ACME").quantity == Decimal("40")


# --------------------------------------------------------------------------- #
# Cancelaciones
# --------------------------------------------------------------------------- #

def _ledger_after_cancel(flex, settings):
    tenant_id, user_id = make_tenant()
    connect(tenant_id, settings)
    sync(tenant_id, user_id)
    flex.statement = fixture("day2_partials.xml")
    sync(tenant_id, user_id)
    flex.statement = fixture("day3_cancel.xml")
    result = sync(tenant_id, user_id)
    return tenant_id, result


def test_cancel_statement_still_imports_and_keeps_position_from_the_broker(flex, settings):
    tenant_id, result = _ledger_after_cancel(flex, settings)
    assert result["status"] == "synced"
    with scoped(tenant_id) as db:
        assert position(db, "ACME").quantity == Decimal("40")
        assert {t.external_id for t in trades(db, "ACME")} >= {"T-1006", "T-1006C"}


def test_cancelled_buy_does_not_count_in_the_ledger(flex, settings):
    tenant_id, _ = _ledger_after_cancel(flex, settings)
    with scoped(tenant_id) as db:
        # El unico efecto neto debe ser el de T-1001 (100) menos las ventas (60).
        assert net_ledger_quantity(db, "ACME") == Decimal("40") == position(db, "ACME").quantity
        original = db.scalar(select(Transaction).where(Transaction.external_id == "T-1006"))
        cancel = db.scalar(select(Transaction).where(Transaction.external_id == "T-1006C"))
        # Ambas filas se conservan para auditoria, ninguna cuenta como compra/venta.
        assert (original.action, cancel.action) == ("cancelled", "cancel")
        assert original.raw_payload["cancelled_by"] == "T-1006C"
        assert cancel.raw_payload["cancels"] == "T-1006"
        assert cancel.quantity == Decimal("10")


def test_cancellation_is_idempotent_and_order_independent(flex, settings):
    tenant_id, user_id = make_tenant()
    connect(tenant_id, settings)
    sync(tenant_id, user_id)
    # La fila de anulacion llega ANTES que la original dentro del mismo XML.
    xml = fixture("day3_cancel.xml")
    first = xml.index('<Trade accountId="U0000001" assetCategory="STK" symbol="ACME" currency="USD" tradeID="T-1006" ')
    second = xml.index('<Trade accountId="U0000001" assetCategory="STK" symbol="ACME" currency="USD" tradeID="T-1006C"')
    end = xml.index("</Trades>")
    flex.statement = xml[:first] + xml[second:end] + xml[first:second] + xml[end:]
    assert sync(tenant_id, user_id)["status"] in {"synced", "partial"}
    with scoped(tenant_id) as db:
        snapshot = sorted((t.external_id, t.action) for t in db.scalars(select(Transaction)))
        assert ("T-1006", "cancelled") in snapshot and ("T-1006C", "cancel") in snapshot
        assert net_ledger_quantity(db, "ACME") == Decimal("100")
    sync(tenant_id, user_id)
    with scoped(tenant_id) as db:
        assert sorted((t.external_id, t.action) for t in db.scalars(select(Transaction))) == snapshot


def test_cancel_of_a_trade_imported_in_an_earlier_statement(flex, settings):
    tenant_id, user_id = make_tenant()
    connect(tenant_id, settings)
    sync(tenant_id, user_id)
    with scoped(tenant_id) as db:
        assert {t.external_id: t.action for t in trades(db, "BETA")} == {"T-1002": "buy"}
    # Dia siguiente: solo llega la anulacion de la compra BETA del dia 1 (origTradeID explicito).
    cancel = (
        '<Trade accountId="U0000001" assetCategory="STK" symbol="BETA" currency="EUR" tradeID="T-1002C" '
        'origTradeID="T-1002" tradeDate="20261026" buySell="BUY (Ca.)" quantity="-50" tradePrice="20.00" '
        'ibCommission="1.00" notes="Ca"/>'
    )
    flex.statement = fixture("day1_initial.xml").replace("</Trades>", cancel + "</Trades>")
    result = sync(tenant_id, user_id)
    with scoped(tenant_id) as db:
        assert {t.external_id: t.action for t in trades(db, "BETA")} == {"T-1002": "cancelled", "T-1002C": "cancel"}
        assert net_ledger_quantity(db, "BETA") == Decimal("0")
    assert result["status"] in {"synced", "partial"}


def test_unmatched_cancellation_is_not_guessed_and_flags_the_import(flex, settings):
    tenant_id, user_id = make_tenant()
    connect(tenant_id, settings, complete_query=True)
    sync(tenant_id, user_id)
    orphan = (
        '<Trade accountId="U0000001" assetCategory="STK" symbol="ACME" currency="USD" tradeID="T-9999C" '
        'tradeDate="20261026" buySell="SELL (Ca.)" quantity="7" tradePrice="99.00" notes="Ca"/>'
    )
    flex.statement = fixture("day1_initial.xml").replace("</Trades>", orphan + "</Trades>")
    result = sync(tenant_id, user_id)
    assert result["status"] == "partial"  # no se declara completo
    with scoped(tenant_id) as db:
        # Nada se neutraliza por aproximacion y la fila huerfana no entra en el libro.
        actions = {t.external_id: t.action for t in trades(db, "ACME")}
        assert actions["T-1001"] == "buy" and "T-9999C" not in actions
        assert net_ledger_quantity(db, "ACME") == Decimal("100")


# --------------------------------------------------------------------------- #
# Diario
# --------------------------------------------------------------------------- #

def test_journal_gets_suggestions_and_ambiguity_never_a_silent_link(flex, settings):
    tenant_id, user_id = make_tenant()
    connect(tenant_id, settings)
    sync(tenant_id, user_id)
    with scoped(tenant_id) as db:
        acme = db.scalar(select(Company).where(Company.ticker == "ACME"))
        buy = DecisionJournalEntry(company_id=acme.id, decision="buy", decision_date=date(2026, 10, 26), rationale="Entrada", price=Decimal("10.00"))
        sell = DecisionJournalEntry(company_id=acme.id, decision="sell", decision_date=date(2026, 10, 27), rationale="Salida parcial", price=Decimal("11.00"))
        hold = DecisionJournalEntry(company_id=acme.id, decision="hold", decision_date=date(2026, 10, 27), rationale="Esperar")
        db.add_all([buy, sell, hold])
        db.commit()
        ids = (buy.id, sell.id, hold.id)

    flex.statement = fixture("day2_partials.xml")
    sync(tenant_id, user_id)

    with scoped(tenant_id) as db:
        buy, sell, hold = (db.get(DecisionJournalEntry, i) for i in ids)
        by_ext = {t.external_id: t.id for t in trades(db, "ACME")}
        # Compra: un unico candidato (T-1001) -> solo SUGERIDO, nunca enlazado solo.
        assert buy.transaction_id is None
        assert buy.metadata_["auto_link"]["status"] == "suggested"
        assert buy.metadata_["auto_link"]["candidate_transaction_id"] == by_ext["T-1001"]
        # Venta con dos ejecuciones parciales el mismo dia: ambigua, el usuario elige.
        assert sell.transaction_id is None
        assert sell.metadata_["auto_link"] == {
            "status": "ambiguous",
            "candidate_transaction_ids": sorted([by_ext["T-1003"], by_ext["T-1004"]]),
            "at": sell.metadata_["auto_link"]["at"],
        }
        # "hold" no tiene operacion: nunca se marca.
        assert hold.transaction_id is None and "auto_link" not in (hold.metadata_ or {})


# --------------------------------------------------------------------------- #
# Cifrado y fugas de token
# --------------------------------------------------------------------------- #

def test_token_is_encrypted_at_rest_and_never_leaks(flex, settings, caplog):
    caplog.set_level(logging.DEBUG)
    tenant_id, user_id = make_tenant()
    view = connect(tenant_id, settings)
    result = sync(tenant_id, user_id)
    with scoped(tenant_id) as db:
        stored = db.scalar(text("select token_ciphertext from ibkr_connections where tenant_id = :t"), {"t": tenant_id})
        everything = repr(service.view(db)) + repr(view) + repr(result)
    assert stored and TOKEN not in stored and stored.startswith("v1:")
    assert decrypt_api_key(stored, settings) == TOKEN
    assert TOKEN not in everything and "token" not in everything.lower()
    assert TOKEN not in caplog.text


def test_flex_failure_keeps_previous_data_and_hides_token_and_provider_text(flex, settings, caplog):
    caplog.set_level(logging.DEBUG)
    tenant_id, user_id = make_tenant()
    connect(tenant_id, settings)
    sync(tenant_id, user_id)
    flex.get_responses = [EXPIRED]
    result = sync(tenant_id, user_id)
    assert result == {"status": "error", "message": "IBKR no disponible; se conservan los datos anteriores."}
    with scoped(tenant_id) as db:
        view = service.view(db)
        assert view["status"] == "error" and view["connected"] is True
        assert "expired" not in view["message"].lower() and TOKEN not in repr(view)
        assert position(db, "ACME").quantity == Decimal("100")  # datos previos intactos
    assert TOKEN not in caplog.text and "Token has expired" not in caplog.text


def test_flex_that_never_finishes_fails_after_bounded_polling(flex, settings):
    tenant_id, user_id = make_tenant()
    connect(tenant_id, settings)
    flex.get_responses = [PENDING] * 50
    before = len(flex.requests)
    assert sync(tenant_id, user_id)["status"] == "error"
    polls = [r for r in flex.requests[before:] if r.url.path.endswith("GetStatement")]
    assert len(polls) == flex_module.IBKRFlexClient.poll_attempts  # acotado, no infinito


def test_wrong_encryption_key_fails_closed_without_importing(flex, settings, monkeypatch):
    tenant_id, user_id = make_tenant()
    connect(tenant_id, settings)
    other = Settings(_env_file=None, app_env="test", llm_settings_encryption_key="another-rotated-key-with-32-bytes-xx")
    monkeypatch.setattr(workers, "get_settings", lambda: other)
    before = len(flex.requests)
    assert sync(tenant_id, user_id)["status"] == "error"
    assert len(flex.requests) == before  # sin clave valida ni siquiera se llama a IBKR
    with scoped(tenant_id) as db:
        assert db.scalar(select(Position)) is None


# --------------------------------------------------------------------------- #
# Rechazos de extracto: cuenta, antiguedad, tenant
# --------------------------------------------------------------------------- #

def test_wrong_account_statement_is_rejected_before_any_write(flex, settings):
    tenant_id, user_id = make_tenant()
    connect(tenant_id, settings)
    flex.statement = fixture("day1_initial.xml").replace("U0000001", "U9999999")
    assert sync(tenant_id, user_id)["status"] == "error"
    with scoped(tenant_id) as db:
        assert db.scalar(select(Transaction)) is None and db.scalar(select(Position)) is None
        assert service.view(db)["last_success_at"] is None


def test_older_statement_cannot_overwrite_a_newer_verified_one(flex, settings):
    tenant_id, user_id = make_tenant()
    connect(tenant_id, settings)
    flex.statement = fixture("day2_partials.xml")
    sync(tenant_id, user_id)
    flex.statement = fixture("day1_initial.xml")  # extracto anterior reentregado
    assert sync(tenant_id, user_id)["status"] == "error"
    with scoped(tenant_id) as db:
        assert position(db, "ACME").quantity == Decimal("40")
        assert service.view(db)["statement_date"] == TODAY


def test_stale_statement_older_than_five_days_is_rejected_at_connect(flex, settings):
    tenant_id, _ = make_tenant()
    flex.statement = fixture("day1_initial.xml").replace("20261026", "20261015")
    with pytest.raises(service.ConnectionError):
        connect(tenant_id, settings)
    with scoped(tenant_id) as db:
        assert service.connection(db) is None  # nada guardado


def test_two_tenants_are_isolated_end_to_end(flex, settings):
    a, user_a = make_tenant()
    b, user_b = make_tenant()
    connect(a, settings)
    sync(a, user_a)
    with scoped(b) as db:
        assert service.view(db)["connected"] is False
        assert db.scalars(select(Transaction)).all() == []
        assert db.scalars(select(IBKRConnection)).all() == []
    # B sin conexion no puede sincronizar con las credenciales de A.
    before = len(flex.requests)
    assert sync(b, user_b)["status"] == "error"
    assert len(flex.requests) == before


# --------------------------------------------------------------------------- #
# Scheduler diario por tenant y desconexion
# --------------------------------------------------------------------------- #

def test_scheduler_registers_daily_job_and_fans_out_only_to_enabled_connections(flex, settings, monkeypatch):
    from app.workers.scheduler import build_scheduler

    job = build_scheduler().get_job("tenant_ibkr_flex_sync")
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert (fields["hour"], fields["minute"]) == ("6", "50")
    assert job.max_instances == 1 and job.coalesce is True

    on, user_on = make_tenant()
    off, user_off = make_tenant()
    none, _ = make_tenant()
    connect(on, settings)
    connect(off, settings)
    with scoped(off) as db:
        service.disconnect(db)
    sent = []
    monkeypatch.setattr(workers.sync_one_tenant_ibkr, "send", lambda *args: sent.append(args))
    outcome = workers.sync_tenant_ibkr_connections.fn()
    assert (on, user_on) in sent and (off, user_off) not in sent
    assert all(args[0] != none for args in sent)
    assert outcome == {"scheduled": len(sent)}


def test_disconnect_erases_token_blocks_sync_and_keeps_imported_data(flex, settings):
    tenant_id, user_id = make_tenant()
    connect(tenant_id, settings)
    sync(tenant_id, user_id)
    with scoped(tenant_id) as db:
        view = service.disconnect(db)
        assert view["connected"] is False and view["status"] == "disconnected"
        assert db.scalar(text("select token_ciphertext from ibkr_connections where tenant_id = :t"), {"t": tenant_id}) is None
    before = len(flex.requests)
    assert sync(tenant_id, user_id)["status"] == "error"
    assert len(flex.requests) == before  # sin token no hay llamada a IBKR
    with scoped(tenant_id) as db:
        assert position(db, "ACME").quantity == Decimal("100")  # datos conservados
        assert len(trades(db, "ACME", "buy")) == 1
