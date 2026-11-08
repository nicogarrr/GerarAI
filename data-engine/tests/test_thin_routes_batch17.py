"""Batch 17: huecos de cobertura de app/api/routes/companies.py (parte 1).

Se llaman las funciones de ruta y los helpers directamente con servicios
doblados; no se levanta HTTP, auth, hilos, ni SEC/Finnhub/Yahoo reales.
NO se prueba: el comportamiento real de analyst_targets/key_stats/
extended_quote/CompanySnapshotService (doblados), la SQL construida pero no
ejecutada (se declara), ni ``run_from_any_context``/``run_in_threadpool``
reales (doblados). Los esquemas de salida CompanyOut y
CompanySnapshotsBatchOut van doblados donde validar exigía una Company
completa: se prueba la logica de la ruta, no el contrato pydantic.

Declaracion de la medicion propia: el modulo tiene 735 sentencias y 176
ramas; este archivo deja 108 sentencias sin ejecutar (84,19% de cobertura
propia). Nada de HTTP, SQL ejecutada ni validacion pydantic real en estos
tests.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy.exc import IntegrityError

import app.api.routes.companies as c
from app.models import DecisionLesson, ManagementPromise


@pytest.fixture(autouse=True)
def _estado_de_dobles_limpio():
    # Los dobles con registro de instancias no acumulan estado entre tests
    # ni lo dejan para otros archivos de la suite.
    yield
    _JournalService.instancias.clear()
    _LearningService.instancias.clear()


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def test_analyst_targets_sin_mapeo_revisado(monkeypatch):
    # Linea 123: ticker sin entrada en REVIEWED_MAP -> devuelve el resultado
    # original (empty) sin probar listados alternativos.
    resultado = SimpleNamespace(status="empty", reason="sin cobertura")
    monkeypatch.setattr(
        c, "analyst_targets_service",
        SimpleNamespace(get=AsyncMock(return_value=resultado)),
    )
    monkeypatch.setattr("app.services.yahoo_fundamentals_service.REVIEWED_MAP", {})
    assert asyncio.run(c.company_analyst_targets("OTC1")) is resultado


def test_analyst_targets_fallback_listado_revisado(monkeypatch):
    original = SimpleNamespace(status="empty")
    alt = SimpleNamespace(
        status="available",
        currency="CAD",
        model_copy=lambda update=None: ("copia", update),
    )
    get = AsyncMock(side_effect=[original, alt])
    monkeypatch.setattr(c, "analyst_targets_service", SimpleNamespace(get=get))
    monkeypatch.setattr(
        "app.services.yahoo_fundamentals_service.REVIEWED_MAP",
        {"KRKNF": {"symbol": "PNG.V", "currency": "CAD"}},
    )
    salida = asyncio.run(c.company_analyst_targets("krknf"))
    assert salida == (
        "copia",
        {
            "symbol": "KRKNF",
            "source": (
                "Yahoo Finance (no oficial) - listado PNG.V en CAD, "
                "agregado de analistas"
            ),
        },
    )


def test_analyst_targets_fallback_divisa_distinta_no_se_adopta(monkeypatch):
    original = SimpleNamespace(status="empty")
    alt = SimpleNamespace(status="available", currency="USD")
    monkeypatch.setattr(
        c, "analyst_targets_service",
        SimpleNamespace(get=AsyncMock(side_effect=[original, alt])),
    )
    monkeypatch.setattr(
        "app.services.yahoo_fundamentals_service.REVIEWED_MAP",
        {"KRKNF": {"symbol": "PNG.V", "currency": "CAD"}},
    )
    assert asyncio.run(c.company_analyst_targets("KRKNF")) is original


def test_key_stats_delega_en_el_servicio(monkeypatch):
    # Linea 155.
    monkeypatch.setattr(
        c, "key_stats_service",
        SimpleNamespace(get=AsyncMock(return_value="stats")),
    )
    assert asyncio.run(c.company_key_stats("ASTS", db=MagicMock())) == "stats"


def test_extended_quote_fallback_listado_revisado(monkeypatch):
    # Lineas 169-175: listado OTC sin cotizacion -> se usa el revisado si la
    # divisa cuadra, declarando simbolo y divisa.
    quote = SimpleNamespace(status="unavailable")
    alt = SimpleNamespace(
        status="ok", price=1.0, currency="CAD", session="abierto",
        model_copy=lambda update=None: ("copia", update),
    )
    monkeypatch.setattr(
        c, "extended_quote_service",
        SimpleNamespace(get=AsyncMock(side_effect=[quote, alt])),
    )
    monkeypatch.setattr(
        "app.services.yahoo_fundamentals_service.REVIEWED_MAP",
        {"KRKNF": {"symbol": "PNG.V", "currency": "CAD"}},
    )
    assert asyncio.run(c.company_extended_quote("krknf", db=MagicMock())) == (
        "copia",
        {
            "ticker": "KRKNF",
            "source": (
                "Yahoo Finance (no oficial) - listado PNG.V en CAD, "
                "retraso posible"
            ),
        },
    )


def _quote_cerrado(**kw):
    base = dict(
        status="ok", session="cerrado", price=10.0, currency="EUR",
        close_change=None, close_change_percent=None, close_change_date=None,
        close_change_previous_date=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _threadpool_real(monkeypatch):
    async def fake(fn):
        return fn()

    monkeypatch.setattr(c, "run_in_threadpool", fake)


def test_extended_quote_cerrado_calcula_close_change(monkeypatch):
    # Lineas 181-201: mercado cerrado -> variacion vs cierres oficiales,
    # convertida a la divisa de la cotizacion.
    quote = _quote_cerrado(currency="GBp")
    monkeypatch.setattr(
        c, "extended_quote_service",
        SimpleNamespace(get=AsyncMock(return_value=quote)),
    )
    _threadpool_real(monkeypatch)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=7))
    monkeypatch.setattr(
        c.market_change, "ticker_close_change",
        lambda db, cid: {
            "currency": "GBP", "change": 0.5, "change_percent": 1.5,
            "date": "2026-11-06", "previous_date": "2026-11-05",
        },
    )
    monkeypatch.setattr(
        "app.valuation.currency.normalize_currency",
        lambda cur: ("GBP", 100 if cur == "GBp" else 1),
    )
    salida = asyncio.run(c.company_extended_quote("ASTS", db=MagicMock()))
    assert salida.close_change == pytest.approx(50.0)
    assert salida.close_change_percent == 1.5
    assert salida.close_change_date == "2026-11-06"
    assert salida.close_change_previous_date == "2026-11-05"


def test_extended_quote_sin_company_no_calcula(monkeypatch):
    quote = _quote_cerrado()
    monkeypatch.setattr(
        c, "extended_quote_service",
        SimpleNamespace(get=AsyncMock(return_value=quote)),
    )
    _threadpool_real(monkeypatch)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    salida = asyncio.run(c.company_extended_quote("ASTS", db=MagicMock()))
    assert salida.close_change is None


def test_extended_quote_error_bd_no_tumba_la_cotizacion(monkeypatch):
    # except Exception -> logger.warning y sigue sin close_change.
    quote = _quote_cerrado()
    monkeypatch.setattr(
        c, "extended_quote_service",
        SimpleNamespace(get=AsyncMock(return_value=quote)),
    )
    _threadpool_real(monkeypatch)
    monkeypatch.setattr(
        c, "resolve_company",
        MagicMock(side_effect=RuntimeError("bd caida")),
    )
    salida = asyncio.run(c.company_extended_quote("ASTS", db=MagicMock()))
    assert salida.close_change is None


def test_extended_quote_divisas_incompatibles_no_mezcla(monkeypatch):
    # Lineas 196-197: la divisa de los cierres no cuadra con la de la
    # cotizacion -> devuelve la cotizacion sin close_change.
    quote = _quote_cerrado()
    monkeypatch.setattr(
        c, "extended_quote_service",
        SimpleNamespace(get=AsyncMock(return_value=quote)),
    )
    _threadpool_real(monkeypatch)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=7))
    monkeypatch.setattr(
        c.market_change, "ticker_close_change",
        lambda db, cid: {"currency": "USD", "change": 2.0, "change_percent": 1.0,
                         "date": "d", "previous_date": "pd"},
    )
    monkeypatch.setattr(
        "app.valuation.currency.normalize_currency",
        lambda cur: (cur, 1),
    )
    salida = asyncio.run(c.company_extended_quote("ASTS", db=MagicMock()))
    assert salida.close_change is None


def test_snapshots_batch_deduplica_y_pide_cada_ticker_una_vez(monkeypatch):
    # Rama 225->223: entradas vacias o repetidas se saltan; el resolver
    # recibe cada ticker normalizado UNA sola vez y en orden de llegada.
    pedidos = []

    def resolver(db, requested):
        pedidos.append(list(requested))
        return ([SimpleNamespace(id=1, ticker="ASTS")], ["FALTA"])

    monkeypatch.setattr(c, "resolve_companies", resolver)
    monkeypatch.setattr(
        c, "CompanySnapshotService",
        lambda: SimpleNamespace(build_many=lambda db, comps: {1: "snap-asts"}),
    )
    monkeypatch.setattr(
        c, "CompanySnapshotsBatchOut",
        lambda snapshots=None, missing=None: (snapshots, missing),
    )
    snapshots, missing = c.company_snapshots_batch(
        tickers="asts, ,ASTS,,falta", db=MagicMock(),
    )
    assert pedidos == [["ASTS", "FALTA"]]
    assert snapshots == {"ASTS": "snap-asts"}
    assert missing == ["FALTA"]


def test_kpi_registry_404(monkeypatch):
    # Lineas 269-271.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException) as exc:
        c.company_kpi_registry("NOPE", db=MagicMock())
    assert exc.value.status_code == 404


def test_kpi_registry_lista_activos(monkeypatch):
    # Linea 272: devuelve los KPI activos de la company (SQL construida, no
    # ejecutada: el scalars va doblado).
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=3))
    db = MagicMock()
    db.scalars.return_value = _Scalars(["kpi-a", "kpi-b"])
    assert c.company_kpi_registry("ASTS", db=db) == ["kpi-a", "kpi-b"]


def test_trust_client_identity_segun_entorno(monkeypatch):
    # Linea 387.
    monkeypatch.setattr(c, "get_settings", lambda: SimpleNamespace(is_production=True))
    assert c._trust_client_identity() is False
    monkeypatch.setattr(c, "get_settings", lambda: SimpleNamespace(is_production=False))
    assert c._trust_client_identity() is True


def test_client_currency_valida_y_canonica(monkeypatch):
    # Lineas 396-398: solo se acepta ISO 4217 o subunidad; lo demas cuenta
    # como no enviado.
    monkeypatch.setattr(c, "is_currency_code", lambda raw: raw in {"gbp", "EUR"})
    monkeypatch.setattr(c, "canonical_currency_code", lambda raw: raw.upper())
    assert c._client_currency("gbp") == "GBP"
    assert c._client_currency("NaN") == ""
    assert c._client_currency(None) == ""


def _ensure_payload(**kw):
    base = dict(ticker="NEWCO", name=None, exchange=None, currency=None,
                sector=None, industry=None, domicile_country=None)
    base.update(kw)
    return c.CompanyEnsureRequest(**base)


def _db_mock():
    db = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    db.add = MagicMock()
    return db


def test_ensure_company_produccion_ignora_identidad_del_cliente(monkeypatch):
    # Lineas 403-405: en produccion el payload se reduce al ticker; la
    # identidad sale del proveedor, nunca del cuerpo.
    monkeypatch.setattr(c, "get_settings", lambda: SimpleNamespace(is_production=True))
    monkeypatch.setattr(c, "CompanyEnrichmentService",
                        lambda: SimpleNamespace(enrich=lambda db, comp: None))
    monkeypatch.setattr(c, "fill_default_currency", lambda comp: None)
    db = _db_mock()
    db.scalar.return_value = None
    company = c.ensure_company(
        _ensure_payload(name="Mentira SA", exchange="BME"), db=db,
    )
    assert company.ticker == "NEWCO"
    assert company.name == "NEWCO"  # nombre del cliente ignorado
    assert company.exchange == "UNKNOWN"


def test_ensure_company_crea_stub_y_enriquece(monkeypatch):
    monkeypatch.setattr(c, "get_settings", lambda: SimpleNamespace(is_production=False))
    enrich = MagicMock()
    monkeypatch.setattr(c, "CompanyEnrichmentService",
                        lambda: SimpleNamespace(enrich=enrich))
    fill = MagicMock()
    monkeypatch.setattr(c, "fill_default_currency", fill)
    db = _db_mock()
    db.scalar.return_value = None
    company = c.ensure_company(
        _ensure_payload(name="Nueva Corp", currency="gbp"), db=db,
    )
    assert company.name == "Nueva Corp"
    assert company.company_type == "research_candidate"
    db.add.assert_called_once_with(company)
    enrich.assert_called_once()
    fill.assert_called_once_with(company)
    db.commit.assert_called_once()


def test_ensure_company_enrich_fallido_no_tumba_el_alta(monkeypatch):
    # Lineas 430-431: el enriquecimiento es best-effort.
    monkeypatch.setattr(c, "get_settings", lambda: SimpleNamespace(is_production=False))
    monkeypatch.setattr(
        c, "CompanyEnrichmentService",
        lambda: SimpleNamespace(
            enrich=MagicMock(side_effect=RuntimeError("finnhub caido")),
        ),
    )
    monkeypatch.setattr(c, "fill_default_currency", lambda comp: None)
    db = _db_mock()
    db.scalar.return_value = None
    company = c.ensure_company(_ensure_payload(), db=db)
    assert company.ticker == "NEWCO"
    db.commit.assert_called_once()


def _fake_enrichment_cls(enrich, needs=True):
    class _Fake:
        needs_enrichment = staticmethod(lambda comp: needs)

        def __init__(self):
            self.enrich = enrich

    return _Fake


def test_ensure_company_existente_actualiza_placeholders(monkeypatch):
    # Lineas 434-452: ficha con identidad placeholder -> se rellena con el
    # payload y se reintenta el enriquecimiento con cooldown.
    existente = SimpleNamespace(
        ticker="NEWCO", name="NEWCO", exchange="UNKNOWN", sector="Unknown",
        industry="Unknown", domicile_country=None,
    )
    monkeypatch.setattr(c, "get_settings", lambda: SimpleNamespace(is_production=False))
    enrich = MagicMock()
    monkeypatch.setattr(c, "CompanyEnrichmentService", _fake_enrichment_cls(enrich))
    db = _db_mock()
    db.scalar.return_value = existente
    salida = c.ensure_company(
        _ensure_payload(name="Nueva Corp", exchange="bme", sector="Tech",
                        industry="Software", domicile_country="Espana"),
        db=db,
    )
    assert salida is existente
    assert existente.name == "Nueva Corp"
    assert existente.exchange == "BME"
    assert existente.sector == "Tech"
    assert existente.industry == "Software"
    assert existente.domicile_country == "Espana"
    enrich.assert_called_once_with(db, existente, respect_cooldown=True)


def test_ensure_company_existente_enrich_fallido_no_tumba(monkeypatch):
    # Lineas 453-454.
    existente = SimpleNamespace(
        ticker="NEWCO", name="Ya SA", exchange="BME", sector="Tech",
        industry="Software", domicile_country="Espana",
    )
    monkeypatch.setattr(c, "get_settings", lambda: SimpleNamespace(is_production=False))
    monkeypatch.setattr(
        c, "CompanyEnrichmentService",
        _fake_enrichment_cls(MagicMock(side_effect=RuntimeError("boom"))),
    )
    db = _db_mock()
    db.scalar.return_value = existente
    assert c.ensure_company(_ensure_payload(), db=db) is existente
    db.commit.assert_called_once()


def test_homonym_conflict_rechaza_identidad_incompatible(monkeypatch):
    # Lineas 483-498: homonimo con nombre incompatible -> motivo de rechazo.
    monkeypatch.setattr(
        "app.services.company_identity_verification.names_compatible",
        lambda a, b: False,
    )
    db = MagicMock()
    db.scalars.return_value = _Scalars(
        [SimpleNamespace(ticker="ALM.MC", name="Almirall SA")],
    )
    motivo = c._homonym_conflict(db, "ALM", "Almonty Industries")
    assert motivo is not None
    assert "ALM.MC" in motivo and "Almirall SA" in motivo


def test_homonym_conflict_sin_conflicto_devuelve_none(monkeypatch):
    monkeypatch.setattr(
        "app.services.company_identity_verification.names_compatible",
        lambda a, b: True,
    )
    db = MagicMock()
    db.scalars.return_value = _Scalars([SimpleNamespace(ticker="ALM", name="Almonty")])
    assert c._homonym_conflict(db, "ALM", "Almonty Industries") is None


def test_identity_lookup_happy(monkeypatch):
    # Lineas 507-530: SEC con coincidencia exacta + perfil del proveedor.
    monkeypatch.setattr(
        "app.services.connectors.sec.SECClient",
        lambda: SimpleNamespace(
            ticker_map=AsyncMock(return_value={"1": {"ticker": "asts", "cik": 1}}),
        ),
    )
    monkeypatch.setattr(
        "app.services.connectors.finnhub.FinnhubClient",
        lambda: SimpleNamespace(
            configured=lambda: True,
            profile=AsyncMock(return_value={"name": "AST SpaceMobile"}),
        ),
    )
    entry, profile, error = asyncio.run(c._identity_lookup("ASTS"))
    assert entry == {"ticker": "asts", "cik": 1}
    assert profile == {"name": "AST SpaceMobile"}
    assert error is None


def test_identity_lookup_fuentes_caidas_fail_closed(monkeypatch):
    # SEC caida -> entry None; proveedor no configurado -> error declarado.
    monkeypatch.setattr(
        "app.services.connectors.sec.SECClient",
        lambda: SimpleNamespace(
            ticker_map=AsyncMock(side_effect=RuntimeError("sec caida")),
        ),
    )
    monkeypatch.setattr(
        "app.services.connectors.finnhub.FinnhubClient",
        lambda: SimpleNamespace(configured=lambda: False),
    )
    entry, profile, error = asyncio.run(c._identity_lookup("ASTS"))
    assert entry is None and profile is None
    assert error == "proveedor_no_configurado"


def test_identity_lookup_proveedor_caido(monkeypatch):
    monkeypatch.setattr(
        "app.services.connectors.sec.SECClient",
        lambda: SimpleNamespace(ticker_map=AsyncMock(return_value={})),
    )
    monkeypatch.setattr(
        "app.services.connectors.finnhub.FinnhubClient",
        lambda: SimpleNamespace(
            configured=lambda: True,
            profile=AsyncMock(side_effect=RuntimeError("finnhub caido")),
        ),
    )
    entry, profile, error = asyncio.run(c._identity_lookup("ASTS"))
    assert entry is None and profile is None
    assert error == "proveedor_no_disponible"


def _run_cerrando(resultado):
    """run_from_any_context doblado que CIERRA la corutina recibida (si no,
    queda 'coroutine was never awaited')."""
    def fake(coro):
        coro.close()
        return resultado
    return fake


def _verdict(**kw):
    base = dict(verified=False, reasons=["proveedor_sin_perfil"], sec=None,
                provider=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _company_model(**kw):
    base = dict(id=1, ticker="ASTS", name="AST", exchange="NASDAQ",
                currency="USD", sector="Tech", industry="Software", cik=None,
                ir_url=None, domicile_country=None,
                company_type="research_candidate", valuation_model="unassigned",
                special_sources=[], special_risks=[], factor_tags=[])
    base.update(kw)
    return c.Company(**base)


def test_identity_verdict_ya_en_maestro(monkeypatch):
    # Lineas 541-550: ficha existente -> verified sin tocar fuentes externas.
    existente = _company_model()
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: existente)
    resp, company = c._identity_verdict(MagicMock(), "ASTS")
    assert resp.verified is True and resp.already_in_master is True
    assert company is existente


def test_identity_verdict_error_proveedor_reemplaza_razon(monkeypatch):
    # Lineas 555-556: proveedor caido sustituye la razon generica.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    monkeypatch.setattr(
        c, "run_from_any_context", _run_cerrando((None, None, "proveedor_no_disponible")),
    )
    monkeypatch.setattr(
        "app.services.company_identity_verification.compare_identities",
        lambda ticker, sec, profile: _verdict(reasons=["proveedor_sin_perfil", "otra"]),
    )
    resp, company = c._identity_verdict(MagicMock(), "ASTS")
    assert resp.reasons == ["proveedor_no_disponible", "otra"]
    assert company is None


def test_identity_verdict_verificado_sin_homonimo(monkeypatch):
    # Lineas 558-575: doble coincidencia sin conflicto -> verified.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    monkeypatch.setattr(
        c, "run_from_any_context",
        _run_cerrando(({"name": "AST"}, {"name": "AST"}, None)),
    )
    monkeypatch.setattr(
        "app.services.company_identity_verification.compare_identities",
        lambda ticker, sec, profile: _verdict(
            verified=True, reasons=["ok"], sec={"name": "AST"}, provider={"p": 1},
        ),
    )
    monkeypatch.setattr(c, "_homonym_conflict", lambda db, t, n: None)
    resp, _ = c._identity_verdict(MagicMock(), "ASTS")
    assert resp.verified is True and resp.sec == {"name": "AST"}


def test_identity_verdict_homonimo_rechaza(monkeypatch):
    # Lineas 559-568.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    monkeypatch.setattr(
        c, "run_from_any_context", _run_cerrando(({"name": "A"}, {"name": "A"}, None)),
    )
    monkeypatch.setattr(
        "app.services.company_identity_verification.compare_identities",
        lambda ticker, sec, profile: _verdict(
            verified=True, reasons=["ok"], sec={"name": "A"}, provider=None,
        ),
    )
    monkeypatch.setattr(c, "_homonym_conflict", lambda db, t, n: "ticker_ambiguo: X")
    resp, company = c._identity_verdict(MagicMock(), "ASTS")
    assert resp.verified is False
    assert "ticker_ambiguo: X" in resp.reasons
    assert company is None


def test_get_identity_verification_usa_el_veredicto(monkeypatch):
    # Lineas 589-590.
    resp = SimpleNamespace(marker="r")
    monkeypatch.setattr(c, "_identity_verdict", lambda db, ticker: (resp, None))
    assert c.get_identity_verification(ticker="asts", db=MagicMock()) is resp


def test_verify_identity_no_verificada_no_crea(monkeypatch):
    # Lineas 605-608.
    resp = c.IdentityVerificationResponse(ticker="ASTS", verified=False)
    monkeypatch.setattr(c, "_identity_verdict", lambda db, ticker: (resp, None))
    db = _db_mock()
    assert c.verify_identity(c.IdentityVerificationRequest(ticker="asts"), db=db) is resp
    db.add.assert_not_called()


def test_verify_identity_crea_ficha_con_procedencia(monkeypatch):
    # Lineas 614-648: doble coincidencia -> stub con identidad de la evidencia.
    resp = c.IdentityVerificationResponse(
        ticker="ASTS", verified=True,
        sec={"name": "AST SpaceMobile, Inc.", "cik": 1780312},
        provider={"name": "AST", "exchange": "nasdaq", "currency": "usd",
                  "country": "US"},
    )
    monkeypatch.setattr(c, "_identity_verdict", lambda db, ticker: (resp, None))
    db = _db_mock()
    # El refresh real poblaria el id; el doble lo simula.
    db.refresh = MagicMock(side_effect=lambda obj: setattr(obj, "id", 1))
    salida = c.verify_identity(c.IdentityVerificationRequest(ticker="asts"), db=db)
    company = db.add.call_args.args[0]
    assert company.ticker == "ASTS"
    assert company.name == "AST SpaceMobile, Inc."
    assert company.exchange == "NASDAQ"
    assert company.currency == "USD"
    assert company.cik == "0001780312"
    assert company.special_sources == ["identity:sec+finnhub"]
    assert salida.company.ticker == "ASTS"
    db.commit.assert_called_once()


def test_verify_identity_doble_clic_idempotente(monkeypatch):
    # Lineas 631-645: IntegrityError en el commit -> la ficha ya existe; se
    # responde como si hubiera estado en el maestro.
    resp = c.IdentityVerificationResponse(
        ticker="ASTS", verified=True,
        sec={"name": "AST", "cik": 1},
        provider={"name": "AST", "exchange": "nasdaq", "currency": "usd",
                  "country": "US"},
    )
    monkeypatch.setattr(c, "_identity_verdict", lambda db, ticker: (resp, None))
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: _company_model())
    db = _db_mock()
    db.commit.side_effect = IntegrityError("stmt", {}, Exception("unique"))
    salida = c.verify_identity(c.IdentityVerificationRequest(ticker="asts"), db=db)
    assert salida.already_in_master is True
    assert salida.company.ticker == "ASTS"
    db.rollback.assert_called_once()


def test_list_companies_devuelve_lista(monkeypatch):
    # Linea 657: lista ordenada (SQL construida, no ejecutada).
    db = MagicMock()
    db.scalars.return_value = _Scalars(["c1", "c2"])
    assert c.list_companies(limit=10, offset=5, db=db) == ["c1", "c2"]


# ---------------------------------------------------------------------------
# Parte 2: resto del modulo (lineas 660-1638).
#
# EXCLUIDOS por las reglas de Nico (alimentan o dependen de tesis/valoracion):
# - changes-since (lee cambios de tesis), long-term-model y su generate,
#   driver-assumptions e inferred-inputs (fcf_margin/wacc/terminal_growth),
#   snapshot/refresh (llama a LongTermModelService y MoatService),
#   expectation-reality (contrasta forecasts del modelo), moat y red-team
#   (analisis sobre la tesis) y refresh/wacc (inputs de WACC).
# ---------------------------------------------------------------------------


def test_like_escape_escapa_comodines():
    # Linea 668: la busqueda LIKE es siempre literal.
    assert c._like_escape("a\\b%c_d") == "a\\\\b\\%c\\_d"


def test_search_companies_construye_query_con_ranking_y_escape(monkeypatch):
    # Lineas 684-705. La SQL va CONSTRUIDA pero NO ejecutada (scalars
    # doblado): lo que se comprueba es la query compilada (ranking CASE de
    # exacto/prefijo, ORDER BY, escape literal de % y _ del termino) y el
    # mapeo a CompanySearchItemOut.
    capturadas = []

    def scalars(query):
        capturadas.append(query)
        return _Scalars([
            SimpleNamespace(ticker="ASTS", name="AST", exchange="NASDAQ",
                            currency="USD"),
        ])

    db = MagicMock()
    db.scalars.side_effect = scalars
    salida = c.search_companies(q="as%_ts", limit=5, db=db)
    sql = str(capturadas[0].compile(compile_kwargs={"literal_binds": True}))
    assert "CASE" in sql and "ORDER BY" in sql
    assert "%as\\%\\_ts%" in sql  # termino escapado: comodines literales
    assert salida.results[0].ticker == "ASTS"
    assert salida.results[0].name == "AST"


def test_basics_batch_deduplica_resuelve_y_reporta_missing(monkeypatch):
    # Lineas 731-756.
    empresas = {"ASTS": SimpleNamespace(
        ticker="ASTS", name="AST", exchange="NASDAQ", currency="USD",
    )}
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: empresas.get(ticker))
    salida = c.companies_basics_batch(tickers="asts,ASTS,, falta ", db=MagicMock())
    assert list(salida.items) == ["ASTS"]
    assert salida.items["ASTS"].name == "AST"
    assert salida.missing == ["FALTA"]


def test_basics_batch_rechaza_mas_del_maximo():
    # Lineas 738-742.
    tickers = ",".join(f"T{i}" for i in range(c.MAX_BASICS_BATCH_TICKERS + 1))
    with pytest.raises(c.HTTPException) as exc:
        c.companies_basics_batch(tickers=tickers, db=MagicMock())
    assert exc.value.status_code == 400


def test_snapshots_batch_rechaza_mas_del_maximo():
    # Rama 229: mas de MAX_SNAPSHOT_BATCH_TICKERS -> 400.
    tickers = ",".join(f"T{i}" for i in range(c.MAX_SNAPSHOT_BATCH_TICKERS + 1))
    with pytest.raises(c.HTTPException) as exc:
        c.company_snapshots_batch(tickers=tickers, db=MagicMock())
    assert exc.value.status_code == 400


def test_get_company_404_y_feliz(monkeypatch):
    # Lineas 762-765.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException) as exc:
        c.get_company("NOPE", db=MagicMock())
    assert exc.value.status_code == 404
    company = SimpleNamespace(ticker="ASTS")
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: company)
    assert c.get_company("ASTS", db=MagicMock()) is company


def test_list_financial_facts_404_y_filtro_metric(monkeypatch):
    # Lineas 775-792: 404 sin company; con company, filtra por metric y
    # devuelve la lista (SQL construida, no ejecutada).
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.list_financial_facts("NOPE", db=MagicMock())
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    db = MagicMock()
    db.scalars.return_value = _Scalars(["hecho"])
    assert c.list_financial_facts("ASTS", metric="revenue", limit=100, db=db) == ["hecho"]
    assert c.list_financial_facts("ASTS", metric=None, limit=100, db=db) == ["hecho"]


def test_financial_terminal_404_y_delega(monkeypatch):
    # Lineas 803-811.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.financial_terminal("NOPE", db=MagicMock())
    company = SimpleNamespace(id=1)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: company)
    build = MagicMock(return_value={"ok": True})
    monkeypatch.setattr(c, "FinancialTerminalService",
                        lambda: SimpleNamespace(build=build))
    salida = c.financial_terminal(
        "ASTS", metrics=" revenue, ,eps ", years=5, periodicity="annual",
        db=MagicMock(),
    )
    assert salida == {"ok": True}
    assert build.call_args.kwargs["metrics"] == ["revenue", "eps"]
    assert build.call_args.kwargs["years"] == 5
    assert build.call_args.kwargs["periodicity"] == "annual"


def test_company_ttm_404_y_delega(monkeypatch):
    # Lineas 828-831.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.company_ttm("NOPE", db=MagicMock())
    company = SimpleNamespace(id=1)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: company)
    monkeypatch.setattr(c, "build_company_ttm", lambda db, comp: {"ttm": 1})
    assert c.company_ttm("ASTS", db=MagicMock()) == {"ttm": 1}


def _metrica_calculada(**kw):
    base = dict(id=1, metric="pe", value=1.5, unit="x", period="annual",
                fiscal_year=2025, fiscal_quarter=None, status="ok",
                definition_version="v1", formula="a/b", numerator=1,
                denominator=2, source_fact_ids=[1], calculation_trace={},
                confidence=1)
    base.update(kw)
    return SimpleNamespace(**base)


def test_list_calculated_metrics_404_vacio_y_con_datos(monkeypatch):
    # Lineas 840-855: not_generated sin metricas, persisted con ellas.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.list_calculated_metrics("NOPE", db=MagicMock())
    company = SimpleNamespace(id=1, ticker="ASTS")
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: company)
    db = MagicMock()
    db.scalars.return_value = _Scalars([])
    salida = c.list_calculated_metrics("ASTS", db=db)
    assert salida["status"] == "not_generated"
    assert salida["metrics"] == []
    db.scalars.return_value = _Scalars([_metrica_calculada()])
    salida = c.list_calculated_metrics("ASTS", db=db)
    assert salida["status"] == "persisted"
    assert salida["metrics"][0].metric == "pe"
    assert salida["metrics"][0].company_id == 1


def test_refresh_calculated_metrics_404_y_feliz(monkeypatch):
    # Lineas 887-891: 404 sin company; feliz recalcula persistiendo.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.refresh_calculated_metrics("NOPE", db=MagicMock())
    company = SimpleNamespace(id=1, ticker="ASTS")
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: company)
    calc = MagicMock(return_value=[_metrica_calculada()])
    monkeypatch.setattr(c, "MetricCalculationService",
                        lambda: SimpleNamespace(calculate_all=calc))
    salida = c.refresh_calculated_metrics("ASTS", db=MagicMock())
    assert salida["status"] == "calculated"
    calc.assert_called_once_with(ANY, company, persist=True)


def test_company_snapshot_404_y_delega(monkeypatch):
    # Lineas 1108-1111.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.company_snapshot("NOPE", db=MagicMock())
    company = SimpleNamespace(id=1)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: company)
    monkeypatch.setattr(c, "CompanySnapshotService",
                        lambda: SimpleNamespace(build=lambda db, comp: "snap"))
    assert c.company_snapshot("ASTS", db=MagicMock()) == "snap"


class _JournalService:
    """Doble de DecisionJournalService: instancia con los metodos usados."""

    instancias: list = []

    def __init__(self):
        self.calls = []
        _JournalService.instancias.append(self)

    def list(self, db, company):
        return ["entrada"]

    def link_transaction(self, db, company, entry_id, transaction_id):
        self.calls.append(("link", entry_id, transaction_id))
        return "entrada"

    def create(self, db, company, **kw):
        self.calls.append(("create", kw))
        return "entrada"


def test_decision_journal_404_y_lista(monkeypatch):
    # Lineas 1131-1136.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.decision_journal("NOPE", db=MagicMock())
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    monkeypatch.setattr(c, "DecisionJournalService", _JournalService)
    monkeypatch.setattr(
        "app.services.journal_trade_link.journal_entry_payload",
        lambda db, entry: {"entry": entry},
    )
    assert c.decision_journal("ASTS", db=MagicMock()) == [{"entry": "entrada"}]


def test_decision_journal_trades_404_y_delega(monkeypatch):
    # Lineas 1142-1147.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.decision_journal_trades("NOPE", db=MagicMock())
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    monkeypatch.setattr(
        "app.services.journal_trade_link.journal_trades",
        lambda db, comp: [{"trade": 1}],
    )
    assert c.decision_journal_trades("ASTS", db=MagicMock()) == [{"trade": 1}]


def test_link_journal_trade_errores_y_feliz(monkeypatch):
    # Lineas 1157-1170: 404 sin company, LookupError -> 404, ValueError -> 422.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException) as exc:
        c.link_decision_journal_trade("NOPE", 1, c.DecisionJournalTradeLink(),
                                      db=MagicMock())
    assert exc.value.status_code == 404
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    monkeypatch.setattr(
        "app.services.journal_trade_link.journal_entry_payload",
        lambda db, entry: {"entry": entry},
    )

    class Roto404(_JournalService):
        def link_transaction(self, db, company, entry_id, transaction_id):
            raise LookupError("no existe")

    class Roto422(_JournalService):
        def link_transaction(self, db, company, entry_id, transaction_id):
            raise ValueError("de otro tenant")

    monkeypatch.setattr(c, "DecisionJournalService", Roto404)
    with pytest.raises(c.HTTPException) as exc:
        c.link_decision_journal_trade("ASTS", 9, c.DecisionJournalTradeLink(),
                                      db=MagicMock())
    assert exc.value.status_code == 404
    monkeypatch.setattr(c, "DecisionJournalService", Roto422)
    with pytest.raises(c.HTTPException) as exc:
        c.link_decision_journal_trade("ASTS", 9, c.DecisionJournalTradeLink(),
                                      db=MagicMock())
    assert exc.value.status_code == 422
    monkeypatch.setattr(c, "DecisionJournalService", _JournalService)
    salida = c.link_decision_journal_trade(
        "ASTS", 9, c.DecisionJournalTradeLink(transaction_id=3), db=MagicMock(),
    )
    assert salida == {"entry": "entrada"}


def test_create_journal_entry_422_y_feliz(monkeypatch):
    # Lineas 1179-1195.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    monkeypatch.setattr(
        "app.services.journal_trade_link.journal_entry_payload",
        lambda db, entry: {"entry": entry},
    )

    class Roto(_JournalService):
        def create(self, db, company, **kw):
            raise ValueError("transaccion ajena")

    monkeypatch.setattr(c, "DecisionJournalService", Roto)
    with pytest.raises(c.HTTPException) as exc:
        c.create_decision_journal_entry(
            "ASTS",
            c.DecisionJournalCreate(decision="buy", rationale="tesis valida"),
            db=MagicMock(),
        )
    assert exc.value.status_code == 422
    monkeypatch.setattr(c, "DecisionJournalService", _JournalService)
    salida = c.create_decision_journal_entry(
        "ASTS",
        c.DecisionJournalCreate(
            decision="buy", rationale="tesis valida",
            what_must_be_true=["  x  ", " ", "y"],
        ),
        db=MagicMock(),
    )
    assert salida == {"entry": "entrada"}
    # Las condiciones van recortadas y sin vacias.
    kw = _JournalService.instancias[-1].calls[0][1]
    assert kw["what_must_be_true"] == ["x", "y"]


def test_decision_lesson_taxonomy_404_y_feliz(monkeypatch):
    # Lineas 1200-1203.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.decision_lesson_taxonomy("NOPE", db=MagicMock())
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    salida = c.decision_lesson_taxonomy("ASTS", db=MagicMock())
    assert salida["taxonomy"] == sorted(c.DECISION_ERROR_TAXONOMY)


class _LearningService:
    """Doble de DecisionLearningService: payload/list de clase, resto de instancia."""

    payload = staticmethod(lambda item: {"p": item})
    list = staticmethod(lambda db, company: ["l1"])

    instancias: list = []

    def __init__(self):
        self.calls = []
        _LearningService.instancias.append(self)

    def propose_from_reviews(self, db, company):
        return ["propuesta"]

    def update(self, db, lesson, **kw):
        self.calls.append(("update", kw))
        return "editada"

    def decide(self, db, lesson, **kw):
        self.calls.append(("decide", kw))
        return "decidida"


def test_decision_lessons_404_y_lista(monkeypatch):
    # Lineas 1208-1211.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.decision_lessons("NOPE", db=MagicMock())
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    monkeypatch.setattr(c, "DecisionLearningService", _LearningService)
    assert c.decision_lessons("ASTS", db=MagicMock()) == [{"p": "l1"}]


def test_propose_decision_lessons_404_y_delega(monkeypatch):
    # Lineas 1221-1224.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.propose_decision_lessons("NOPE", db=MagicMock())
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    monkeypatch.setattr(c, "DecisionLearningService", _LearningService)
    assert c.propose_decision_lessons("ASTS", db=MagicMock()) == [{"p": "propuesta"}]


def _lesson(company_id=1):
    # Modelo real, no SimpleNamespace: el gate de tenant/company se prueba de verdad.
    return DecisionLesson(company_id=company_id)


def _payload_lesson():
    return c.DecisionLessonUpdate(
        taxonomy="selling_too_early", cause="causa", error="error",
        lesson="leccion", future_application="aplicacion",
    )


def test_update_decision_lesson_404s_409_y_feliz(monkeypatch):
    # Lineas 1237-1253: 404 sin company, sin lesson o de otra company;
    # ValueError -> 409.
    db = MagicMock()
    db.get.return_value = _lesson()
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.update_decision_lesson("NOPE", 1, _payload_lesson(), db=db)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    db.get.return_value = None
    with pytest.raises(c.HTTPException):
        c.update_decision_lesson("ASTS", 1, _payload_lesson(), db=db)
    db.get.return_value = _lesson(company_id=2)
    with pytest.raises(c.HTTPException):
        c.update_decision_lesson("ASTS", 1, _payload_lesson(), db=db)
    db.get.return_value = _lesson()

    class Roto(_LearningService):
        def update(self, db, lesson, **kw):
            raise ValueError("ya decidida")

    monkeypatch.setattr(c, "DecisionLearningService", Roto)
    with pytest.raises(c.HTTPException) as exc:
        c.update_decision_lesson("ASTS", 1, _payload_lesson(), db=db)
    assert exc.value.status_code == 409
    monkeypatch.setattr(c, "DecisionLearningService", _LearningService)
    salida = c.update_decision_lesson("ASTS", 1, _payload_lesson(), db=db)
    assert salida == {"p": "editada"}


def test_decide_decision_lesson_404_409_y_feliz(monkeypatch):
    # Lineas 1263-1276: el actor sale de db.info (user_id o "local-user").
    db = MagicMock()
    db.info = {"user_id": "u-1"}
    db.get.return_value = _lesson()
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))

    class Roto(_LearningService):
        def decide(self, db, lesson, **kw):
            raise ValueError("ya aprobada")

    monkeypatch.setattr(c, "DecisionLearningService", Roto)
    with pytest.raises(c.HTTPException) as exc:
        c.decide_decision_lesson("ASTS", 1, c.DecisionLessonAction(action="approve"),
                                 db=db)
    assert exc.value.status_code == 409
    monkeypatch.setattr(c, "DecisionLearningService", _LearningService)
    salida = c.decide_decision_lesson(
        "ASTS", 1, c.DecisionLessonAction(action="reject"), db=db,
    )
    assert salida == {"p": "decidida"}
    servicio = _LearningService.instancias[-1]
    assert servicio.calls[0][1] == {"action": "reject", "actor": "u-1"}


class _Credibilidad:
    """Doble de ManagementCredibilityService: payload de clase, resto instancia."""

    payload = staticmethod(lambda row: {"row": row})

    def dashboard(self, db, company):
        return {"dashboard": 1}

    def register(self, db, company, **kw):
        return "promesa"

    def import_call_claims(self, db, company):
        return ["claim"]

    def reconcile(self, db, company):
        self.reconciliado = True

    def set_explanation(self, db, promise, explanation):
        return "explicada"


def test_management_credibility_404_y_dashboard(monkeypatch):
    # Lineas 1281-1284.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.management_credibility("NOPE", db=MagicMock())
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    monkeypatch.setattr(c, "ManagementCredibilityService", _Credibilidad)
    assert c.management_credibility("ASTS", db=MagicMock()) == {"dashboard": 1}


def test_register_management_promise_400_y_feliz(monkeypatch):
    # Lineas 1293-1302: ValueError -> 400; feliz devuelve el payload.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))

    class Roto(_Credibilidad):
        def register(self, db, company, **kw):
            raise ValueError("metrica desconocida")

    monkeypatch.setattr(c, "ManagementCredibilityService", Roto)
    from datetime import date as _date
    promesa = c.ManagementPromiseCreate(
        promise="Doblar ingresos", promise_date=_date(2026, 1, 15),
        expected_period="FY2027",
    )
    with pytest.raises(c.HTTPException) as exc:
        c.register_management_promise("ASTS", promesa, db=MagicMock())
    assert exc.value.status_code == 400
    monkeypatch.setattr(c, "ManagementCredibilityService", _Credibilidad)
    salida = c.register_management_promise("ASTS", promesa, db=MagicMock())
    assert salida == {"row": "promesa"}


def test_import_call_claims_404_y_delega(monkeypatch):
    # Lineas 1309-1315.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.import_management_call_claims("NOPE", db=MagicMock())
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    monkeypatch.setattr(c, "ManagementCredibilityService", _Credibilidad)
    assert c.import_management_call_claims("ASTS", db=MagicMock()) == [{"row": "claim"}]


def test_reconcile_management_promises_404_y_feliz(monkeypatch):
    # Lineas 1322-1326: reconcilia y devuelve el dashboard resultante.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.reconcile_management_promises("NOPE", db=MagicMock())
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    monkeypatch.setattr(c, "ManagementCredibilityService", _Credibilidad)
    assert c.reconcile_management_promises("ASTS", db=MagicMock()) == {"dashboard": 1}


def test_update_management_explanation_404s_y_feliz(monkeypatch):
    # Lineas 1336-1343.
    db = MagicMock()
    # Modelos reales (ManagementPromise), no SimpleNamespace: el gate de
    # company_id se prueba de verdad.
    db.get.return_value = ManagementPromise(company_id=1)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException) as exc:
        c.update_management_explanation(
            "NOPE", 1, c.ManagementExplanationUpdate(explanation="contexto"),
            db=db,
        )
    assert exc.value.status_code == 404
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    db.get.return_value = ManagementPromise(company_id=2)
    with pytest.raises(c.HTTPException):
        c.update_management_explanation(
            "ASTS", 1, c.ManagementExplanationUpdate(explanation="contexto"), db=db,
        )
    db.get.return_value = ManagementPromise(company_id=1)
    monkeypatch.setattr(c, "ManagementCredibilityService", _Credibilidad)
    salida = c.update_management_explanation(
        "ASTS", 1, c.ManagementExplanationUpdate(explanation="contexto"), db=db,
    )
    assert salida == {"row": "explicada"}


def test_peer_comparison_404_metricas_y_delega(monkeypatch):
    # Lineas 1393-1399: GET solo lectura (refresh=False); metricas por
    # defecto cuando no se piden.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.peer_comparison("NOPE", db=MagicMock())
    company = SimpleNamespace(id=1)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: company)
    compare = MagicMock(return_value={"peers": []})
    monkeypatch.setattr(c, "PeerComparisonService",
                        lambda: SimpleNamespace(compare=compare))
    c.peer_comparison("ASTS", metrics=" pe, ,pb ", limit=8, db=MagicMock())
    assert compare.call_args.kwargs["metrics"] == ["pe", "pb"]
    assert compare.call_args.kwargs["refresh"] is False
    c.peer_comparison("ASTS", metrics=None, limit=8, db=MagicMock())
    assert compare.call_args.kwargs["metrics"] == c.DEFAULT_PEER_METRICS


def test_refresh_peer_comparison_404_y_delega(monkeypatch):
    # Lineas 1415-1420: POST recalcula y persiste (refresh=True).
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.refresh_peer_comparison("NOPE", db=MagicMock())
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    compare = MagicMock(return_value={"peers": ["X"]})
    monkeypatch.setattr(c, "PeerComparisonService",
                        lambda: SimpleNamespace(compare=compare))
    salida = c.refresh_peer_comparison("ASTS", metrics=None, limit=8, db=MagicMock())
    assert salida == {"peers": ["X"]}
    assert compare.call_args.kwargs["refresh"] is True


def test_peer_analysis_404_y_delega(monkeypatch):
    # Lineas 1435-1438.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.peer_analysis("NOPE", db=MagicMock())
    company = SimpleNamespace(id=1)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: company)
    monkeypatch.setattr(
        c, "PeerAnalysisService",
        lambda: SimpleNamespace(analyze=lambda db, comp, limit: {"a": limit}),
    )
    assert c.peer_analysis("ASTS", limit=3, db=MagicMock()) == {"a": 3}


def _threadpool_ejecutor(monkeypatch):
    async def fake(fn):
        return fn()

    monkeypatch.setattr(c, "run_in_threadpool", fake)
    monkeypatch.setattr(c, "run_from_any_context", lambda resultado: resultado)


def _http_status_error(status):
    req = httpx.Request("GET", "https://proveedor.example/x?apikey=SECRETO")
    return httpx.HTTPStatusError("fallo", request=req,
                                 response=httpx.Response(status, request=req))


def test_refresh_fmp_404_y_feliz(monkeypatch):
    # Lineas 1507-1540: todo en el pool; la corutina del servicio puentea.
    _threadpool_ejecutor(monkeypatch)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException) as exc:
        asyncio.run(c.refresh_fmp_financials("NOPE", db=MagicMock()))
    assert exc.value.status_code == 404
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    refresh = MagicMock(return_value={"facts_imported": 3})
    monkeypatch.setattr(c, "FinancialIngestionService",
                        lambda: SimpleNamespace(refresh_from_fmp=refresh))
    monkeypatch.setattr(c, "FMPClient", lambda: SimpleNamespace())
    salida = asyncio.run(c.refresh_fmp_financials("ASTS", db=MagicMock()))
    assert salida == {"facts_imported": 3}


def test_refresh_fmp_error_sanitizado(monkeypatch):
    # RuntimeError -> 424 con detalle saneado (nunca la URL con la api key).
    _threadpool_ejecutor(monkeypatch)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    monkeypatch.setattr(
        c, "FinancialIngestionService",
        lambda: SimpleNamespace(
            refresh_from_fmp=MagicMock(
                side_effect=RuntimeError("https://x?apikey=SECRETO caido"),
            ),
        ),
    )
    monkeypatch.setattr(c, "FMPClient", lambda: SimpleNamespace())
    with pytest.raises(c.HTTPException) as exc:
        asyncio.run(c.refresh_fmp_financials("ASTS", db=MagicMock()))
    assert exc.value.status_code == 424
    assert "SECRETO" not in str(exc.value.detail)


def test_refresh_fmp_402_plan_y_otro_status(monkeypatch):
    # 402 del plan gratuito -> 424 accionable; otro status -> 424 generico.
    _threadpool_ejecutor(monkeypatch)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    monkeypatch.setattr(c, "FMPClient", lambda: SimpleNamespace())
    for status in (402, 500):
        monkeypatch.setattr(
            c, "FinancialIngestionService",
            lambda: SimpleNamespace(
                refresh_from_fmp=MagicMock(
                    side_effect=_http_status_error(status),
                ),
            ),
        )
        with pytest.raises(c.HTTPException) as exc:
            asyncio.run(c.refresh_fmp_financials("ASTS", db=MagicMock()))
        assert exc.value.status_code == 424
        assert "SECRETO" not in str(exc.value.detail)


def test_refresh_sec_completa_el_contrato(monkeypatch):
    # Lineas 1545-1564: la via SEC no importa statements; el resumen se
    # calcula aqui (latest_periods y valuation_input_ready del servicio).
    _threadpool_ejecutor(monkeypatch)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    servicio = SimpleNamespace(
        refresh_from_sec=lambda db, company: {"facts_imported": 2},
        latest_periods=lambda db, company: {"revenue": "2025Q3"},
        valuation_input_ready=lambda db, company: True,
    )
    monkeypatch.setattr(c, "FinancialIngestionService", lambda: servicio)
    salida = asyncio.run(c.refresh_sec_financials("ASTS", db=MagicMock()))
    assert salida["facts_imported"] == 2
    assert salida["statements_imported"] == 0
    assert salida["latest_periods"] == {"revenue": "2025Q3"}
    assert salida["valuation_input_ready"] is True


def test_refresh_sec_404_y_error_sanitizado(monkeypatch):
    _threadpool_ejecutor(monkeypatch)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        asyncio.run(c.refresh_sec_financials("NOPE", db=MagicMock()))
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    monkeypatch.setattr(
        c, "FinancialIngestionService",
        lambda: SimpleNamespace(
            refresh_from_sec=MagicMock(
                side_effect=RuntimeError("https://x?apikey=SECRETO"),
            ),
        ),
    )
    with pytest.raises(c.HTTPException) as exc:
        asyncio.run(c.refresh_sec_financials("ASTS", db=MagicMock()))
    assert exc.value.status_code == 424
    assert "SECRETO" not in str(exc.value.detail)


def test_refresh_esef_404_feliz_y_error(monkeypatch):
    # Lineas 1571-1587.
    _threadpool_ejecutor(monkeypatch)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        asyncio.run(c.refresh_esef_financials("NOPE", db=MagicMock()))
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    monkeypatch.setattr(
        c, "FinancialIngestionService",
        lambda: SimpleNamespace(
            refresh_from_esef=lambda db, company: {"facts_imported": 5},
        ),
    )
    salida = asyncio.run(c.refresh_esef_financials("SAN.MC", db=MagicMock()))
    assert salida["facts_imported"] == 5
    assert salida["statements_imported"] == 0
    monkeypatch.setattr(
        c, "FinancialIngestionService",
        lambda: SimpleNamespace(
            refresh_from_esef=MagicMock(
                side_effect=RuntimeError("https://x?apikey=SECRETO"),
            ),
        ),
    )
    with pytest.raises(c.HTTPException) as exc:
        asyncio.run(c.refresh_esef_financials("SAN.MC", db=MagicMock()))
    assert exc.value.status_code == 424
    assert "SECRETO" not in str(exc.value.detail)


def test_refresh_yahoo_fundamentals_404_feliz_y_error(monkeypatch):
    # Lineas 1594-1610: fundamentales no oficiales del mapa revisado.
    _threadpool_ejecutor(monkeypatch)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        asyncio.run(c.refresh_yahoo_fundamentals("NOPE", db=MagicMock()))
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: SimpleNamespace(id=1))
    monkeypatch.setattr(
        "app.services.yahoo_fundamentals_service.refresh_from_yahoo",
        lambda db, company: {"facts_imported": 4},
    )
    servicio = SimpleNamespace(
        latest_periods=lambda db, company: {"revenue": "FY2025"},
        valuation_input_ready=lambda db, company: False,
    )
    monkeypatch.setattr(c, "FinancialIngestionService", lambda: servicio)
    salida = asyncio.run(c.refresh_yahoo_fundamentals("KRKNF", db=MagicMock()))
    assert salida["facts_imported"] == 4
    assert salida["statements_imported"] == 0
    assert salida["valuation_input_ready"] is False
    monkeypatch.setattr(
        "app.services.yahoo_fundamentals_service.refresh_from_yahoo",
        MagicMock(side_effect=RuntimeError("https://x?apikey=SECRETO")),
    )
    with pytest.raises(c.HTTPException) as exc:
        asyncio.run(c.refresh_yahoo_fundamentals("KRKNF", db=MagicMock()))
    assert exc.value.status_code == 424
    assert "SECRETO" not in str(exc.value.detail)


def test_company_share_capital_404_y_feliz(monkeypatch):
    # Lineas 1633-1638: 404 con detalle de ui_error; feliz delega.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException) as exc:
        c.company_share_capital("NOPE", db=MagicMock())
    assert exc.value.status_code == 404
    company = SimpleNamespace(id=1)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: company)
    monkeypatch.setattr(
        "app.services.share_capital_service.build_share_capital",
        lambda db, comp: {"shares": 10},
    )
    assert c.company_share_capital("ASTS", db=MagicMock()) == {"shares": 10}


# ---------------------------------------------------------------------------
# Parte 3: delegaciones y arcos sueltos restantes.
#
# EXCLUIDO ademas: thesis_tickers (251-262): lee la tabla de tesis para
# ordenar el indice de research; depende de datos de tesis (regla de Nico).
# ---------------------------------------------------------------------------


def test_analyst_targets_con_datos_devuelve_directo(monkeypatch):
    # Linea 114: status distinto de "empty" -> sin fallback.
    resultado = SimpleNamespace(status="available")
    monkeypatch.setattr(
        c, "analyst_targets_service",
        SimpleNamespace(get=AsyncMock(return_value=resultado)),
    )
    assert asyncio.run(c.company_analyst_targets("ASTS")) is resultado


def test_analyst_history_delega(monkeypatch):
    # Linea 147.
    monkeypatch.setattr(
        c, "analyst_history_service",
        SimpleNamespace(get=AsyncMock(return_value="historia")),
    )
    assert asyncio.run(c.company_analyst_history("ASTS")) == "historia"


def test_extended_quote_fallback_alt_no_disponible_sigue(monkeypatch):
    # Arcos 172->181 y 174->181: hay listado revisado pero el alternativo
    # tampoco cotiza -> se sigue con la cotizacion original.
    quote = _quote_cerrado(status="unavailable", session="cerrado", price=None)
    alt = SimpleNamespace(status="unavailable")
    monkeypatch.setattr(
        c, "extended_quote_service",
        SimpleNamespace(get=AsyncMock(side_effect=[quote, alt])),
    )
    monkeypatch.setattr(
        "app.services.yahoo_fundamentals_service.REVIEWED_MAP",
        {"KRKNF": {"symbol": "PNG.V", "currency": "CAD"}},
    )
    salida = asyncio.run(c.company_extended_quote("KRKNF", db=MagicMock()))
    assert salida is quote


def test_extended_quote_sesion_abierta_sin_close_change(monkeypatch):
    # Arco 181->202: mercado abierto -> nunca se calcula close_change.
    quote = _quote_cerrado(session="abierto")
    monkeypatch.setattr(
        c, "extended_quote_service",
        SimpleNamespace(get=AsyncMock(return_value=quote)),
    )
    salida = asyncio.run(c.company_extended_quote("ASTS", db=MagicMock()))
    assert salida.close_change is None


def test_sync_kpi_registry_404_y_delega(monkeypatch):
    # Lineas 285-288.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException):
        c.sync_company_kpi_registry("NOPE", db=MagicMock())
    company = SimpleNamespace(id=1)
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: company)
    sync = MagicMock(return_value=["kpi"])
    monkeypatch.setattr(c, "CompanyKPIRegistryService",
                        lambda: SimpleNamespace(sync=sync))
    assert c.sync_company_kpi_registry("ASTS", db=MagicMock()) == ["kpi"]
    sync.assert_called_once_with(ANY, company)


def test_ensure_company_sin_necesidad_no_enriquece(monkeypatch):
    # Arco 448->455: needs_enrichment False -> ni una llamada al proveedor.
    existente = SimpleNamespace(
        ticker="NEWCO", name="Ya SA", exchange="BME", sector="Tech",
        industry="Software", domicile_country="Espana",
    )
    monkeypatch.setattr(c, "get_settings", lambda: SimpleNamespace(is_production=False))
    enrich = MagicMock()
    monkeypatch.setattr(c, "CompanyEnrichmentService",
                        _fake_enrichment_cls(enrich, needs=False))
    db = _db_mock()
    db.scalar.return_value = existente
    assert c.ensure_company(_ensure_payload(), db=db) is existente
    enrich.assert_not_called()
    db.commit.assert_called_once()


def test_identity_lookup_mapeo_sec_sin_coincidencia(monkeypatch):
    # Arco 514->513: entradas no dict o de otro ticker -> entry None.
    monkeypatch.setattr(
        "app.services.connectors.sec.SECClient",
        lambda: SimpleNamespace(
            ticker_map=AsyncMock(return_value={
                "1": "no-dict",
                "2": {"ticker": "OTRO"},
            }),
        ),
    )
    monkeypatch.setattr(
        "app.services.connectors.finnhub.FinnhubClient",
        lambda: SimpleNamespace(
            configured=lambda: True, profile=AsyncMock(return_value=None),
        ),
    )
    entry, profile, error = asyncio.run(c._identity_lookup("ASTS"))
    assert entry is None and profile is None and error is None


def test_verify_identity_integrity_error_sin_ganador_relancia(monkeypatch):
    # Linea 640: doble clic sin ficha ganadora (carrera rara) -> se relanza.
    resp = c.IdentityVerificationResponse(
        ticker="ASTS", verified=True,
        sec={"name": "AST", "cik": 1},
        provider={"name": "AST", "exchange": "nasdaq", "currency": "usd",
                  "country": "US"},
    )
    monkeypatch.setattr(c, "_identity_verdict", lambda db, ticker: (resp, None))
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    db = _db_mock()
    db.commit.side_effect = IntegrityError("stmt", {}, Exception("unique"))
    with pytest.raises(IntegrityError):
        c.verify_identity(c.IdentityVerificationRequest(ticker="asts"), db=db)
    db.rollback.assert_called_once()


def test_create_journal_entry_404(monkeypatch):
    # Linea 1181.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    with pytest.raises(c.HTTPException) as exc:
        c.create_decision_journal_entry(
            "NOPE",
            c.DecisionJournalCreate(decision="buy", rationale="tesis valida"),
            db=MagicMock(),
        )
    assert exc.value.status_code == 404


def test_decide_decision_lesson_404_sin_company(monkeypatch):
    # Linea 1266.
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    db = MagicMock()
    db.info = {}
    db.get.return_value = _lesson()
    with pytest.raises(c.HTTPException) as exc:
        c.decide_decision_lesson("NOPE", 1, c.DecisionLessonAction(action="approve"),
                                 db=db)
    assert exc.value.status_code == 404


def test_register_management_promise_404(monkeypatch):
    # Linea 1295.
    from datetime import date as _date
    monkeypatch.setattr(c, "resolve_company", lambda db, ticker: None)
    promesa = c.ManagementPromiseCreate(
        promise="Doblar ingresos", promise_date=_date(2026, 1, 15),
        expected_period="FY2027",
    )
    with pytest.raises(c.HTTPException) as exc:
        c.register_management_promise("NOPE", promesa, db=MagicMock())
    assert exc.value.status_code == 404


def test_extended_quote_sin_mapeo_revisado_devuelve_quote(monkeypatch):
    # Arco 172->181: ticker sin listado revisado -> sin fallback.
    quote = SimpleNamespace(status="unavailable", session="cerrado", price=None)
    monkeypatch.setattr(
        c, "extended_quote_service",
        SimpleNamespace(get=AsyncMock(return_value=quote)),
    )
    monkeypatch.setattr("app.services.yahoo_fundamentals_service.REVIEWED_MAP", {})
    salida = asyncio.run(c.company_extended_quote("OTC1", db=MagicMock()))
    assert salida is quote
