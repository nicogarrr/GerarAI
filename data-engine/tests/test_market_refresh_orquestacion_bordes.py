"""market_refresh_service: bordes de la orquestacion refresh() con SQLite real.

Segunda PR del modulo (la primera cubrio los providers sin DB). Zona
SOLO-tests del encargo: los consumidores de valoracion van doblados y
declarados, nunca se ejecuta valoracion real.

Cubierto aqui:
- _official_fx: divisa sin tipo y sin error previo -> rate_not_available.
- Etapa de precios: barra existente con quote_currency distinta y conversion
  imposible -> incompatible_bar_unit (no se toca la barra); actualizacion
  con volumen nuevo -> pisa el volumen.
- Etapa FX: sin empresas ni posiciones se salta el bloque de unidades de
  hechos; base USD (!= TAX_CURRENCY) escribe ademas los tipos fiscales en
  EUR y salta las divisas sin tipo; excepcion del proveedor -> rollback y
  error "ECB" clasificado.
- Etapa de revalorizacion: posicion sin precio de mercado ->
  missing_market_price; posicion con valuation_hold_reason -> se declara y
  se salta la conversion.
- Etapa de pantallas: saved screen que corre bien -> screen_results con
  matches y nuevos ids exactos.

Dobles declarados: price_provider/fx_provider inyectados; PortfolioFXService
(base_currency + upsert_rate espia, sin FX real); PortfolioSnapshotService,
RiskService, AlertRuleService y ScreenerService (consumidores de metricas:
nunca se ejecutan); price_in_currency (conversion imposible simulada);
fetch_official_quotes/to_base_rates; invalidate_*_cache de app.core.cache
(no-ops: no tocan Redis). Tenant real en SQLite con db.info["tenant_id"].
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.market_refresh_service as mrs
from app.models.entities import (
    Base,
    Company,
    FXRate,
    MarketPrice,
    Position,
    SavedScreen,
    Tenant,
)
from app.services.market_refresh_service import (
    MarketRefreshService,
    PriceObservation,
)

AS_OF = date(2026, 11, 8)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="t-mr", name="t-mr")
        session.add(tenant)
        session.commit()
        session.info["tenant_id"] = tenant.id
        yield session
    engine.dispose()


@pytest.fixture(autouse=True)
def _consumidores_doblados(monkeypatch):
    """Todos los consumidores de metricas/valoracion y caches: doblados."""
    monkeypatch.setattr(
        "app.services.portfolio_snapshot_service.PortfolioSnapshotService",
        lambda: SimpleNamespace(
            capture=lambda db, as_of, source: SimpleNamespace(
                id=1, pricing_coverage=1.0
            )
        ),
    )
    monkeypatch.setattr(
        mrs, "RiskService",
        lambda: SimpleNamespace(dashboard=lambda db: {"status": "ok"}),
    )
    monkeypatch.setattr(
        mrs, "AlertRuleService",
        lambda: SimpleNamespace(evaluate_all=lambda db: []),
    )
    monkeypatch.setattr(
        "app.core.cache.invalidate_market_data_cache", lambda: None
    )
    monkeypatch.setattr(
        "app.core.cache.invalidate_portfolio_cache", lambda db=None: None
    )
    # El listener after_commit de core.cache_invalidation conserva la
    # referencia importada de invalidate_portfolio_cache, asi que el doble de
    # arriba no lo intercepta: se dobla el punto comun _redis_client (None =
    # desactivado determinista, sin intento real a localhost:6379).
    monkeypatch.setattr("app.core.cache._redis_client", lambda: None)


class _FXServicioEspia:
    def __init__(self, base="EUR"):
        self._base = base
        self.upserts = []

    def base_currency(self, db):
        return self._base

    def upsert_rate(self, db, *, base_currency, quote_currency, rate, rate_date, source):
        self.upserts.append((base_currency, quote_currency))

    def fx_table(self, db, *, currencies, base_currency, as_of_max):
        return {}


class _PriceProvider:
    def __init__(self, observations=None, errors=None):
        self._observations = observations or {}
        self._errors = errors or []

    async def fetch(self, companies, *, as_of):
        return self._observations, self._errors


class _FXProvider:
    def __init__(self, rates_por_base=None, exc=None):
        self._rates = rates_por_base or {}
        self._exc = exc
        self.calls = []

    async def fetch(self, *, base_currency, quote_currencies):
        self.calls.append((base_currency, set(quote_currencies)))
        if self._exc is not None:
            raise self._exc
        return SimpleNamespace(
            rates=self._rates.get(base_currency, {}), rate_date=AS_OF
        )


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=f"{ticker} Inc.", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", cik="0000320193",
        company_type="holding", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _servicio(monkeypatch, fx_base="EUR", fx_rates=None, fx_exc=None, observations=None):
    fx_espia = _FXServicioEspia(base=fx_base)
    monkeypatch.setattr(mrs, "PortfolioFXService", lambda: fx_espia)
    fx_provider = _FXProvider(rates_por_base=fx_rates, exc=fx_exc)
    servicio = MarketRefreshService(
        price_provider=_PriceProvider(observations=observations),
        fx_provider=fx_provider,
    )
    return servicio, fx_espia, fx_provider


@pytest.mark.anyio
async def test_official_fx_divisa_sin_tipo_registra_motivo(db, monkeypatch):
    async def _sin_quotes(currencies, on, **kwargs):
        return {}, []

    monkeypatch.setattr(mrs, "fetch_official_quotes", _sin_quotes)
    monkeypatch.setattr(mrs, "to_base_rates", lambda *a, **k: {})
    servicio, fx_espia, _ = _servicio(monkeypatch)
    fx_errors = []

    written = await servicio._official_fx(
        db, fx_espia, "EUR", {"GEL"},
        SimpleNamespace(rates={}, rate_date=AS_OF), AS_OF, fx_errors,
    )

    assert written == 0
    assert fx_errors == [{"currency": "GEL", "reason": "rate_not_available"}]
    assert fx_espia.upserts == []


@pytest.mark.anyio
async def test_refresh_barra_unidad_incompatible_y_volumen_nuevo(db, monkeypatch):
    company_a = _company(db, "AAPL")
    company_b = _company(db, "MSFT")
    for company in (company_a, company_b):
        db.add(MarketPrice(
            company_id=company.id, date=AS_OF, open=1, high=1, low=1,
            close=Decimal("100"), volume=100, source="FMP", quote_currency="USD",
        ))
    db.commit()
    # Conversion imposible para la barra con otra unidad; identidad si cuadra.
    monkeypatch.setattr(mrs, "price_in_currency", lambda *a, **k: None)
    observations = {
        "AAPL": PriceObservation(
            "AAPL", Decimal("101"), AS_OF, "FMP", volume=500, quote_currency="GBP",
        ),
        "MSFT": PriceObservation(
            "MSFT", Decimal("102"), AS_OF, "FMP", volume=500, quote_currency="USD",
        ),
    }
    servicio, _, _ = _servicio(monkeypatch, observations=observations)

    resultado = await servicio.refresh(db, as_of=AS_OF, companies=[company_a, company_b])

    etapa_precios = resultado["stages"][0]
    assert etapa_precios["status"] == "partial"
    assert etapa_precios["errors"] == [
        {"ticker": "AAPL", "reason": "incompatible_bar_unit"}
    ]
    barra_a = db.query(MarketPrice).filter_by(company_id=company_a.id).one()
    assert barra_a.close == Decimal("100")
    assert barra_a.volume == 100
    barra_b = db.query(MarketPrice).filter_by(company_id=company_b.id).one()
    # Unidad coincidente: close y volumen se actualizan con el dato nuevo
    # (la conversion doblada a None solo aplica con unidad distinta).
    assert barra_b.close == Decimal("102")
    assert barra_b.volume == 500


@pytest.mark.anyio
async def test_refresh_sin_empresas_salta_bloque_de_unidades(db, monkeypatch):
    servicio, _, fx_provider = _servicio(monkeypatch)

    resultado = await servicio.refresh(db, as_of=AS_OF, companies=[])

    assert resultado["stages"][1]["name"] == "update_fx"
    assert fx_provider.calls == [("EUR", set())]


@pytest.mark.anyio
async def test_refresh_base_usd_escribe_tipos_fiscales_en_eur(db, monkeypatch):
    company = _company(db, "AAPL")
    position = Position(
        tenant_id=db.info["tenant_id"], company_id=company.id,
        quantity=Decimal("1"), currency="GBP", base_currency="USD",
    )
    db.add(position)
    db.commit()
    fx_rates = {
        "USD": {"GBP": Decimal("0.79")},
        "EUR": {"GBP": Decimal("1.20"), "USD": None},
    }
    servicio, fx_espia, fx_provider = _servicio(
        monkeypatch, fx_base="USD", fx_rates=fx_rates
    )

    resultado = await servicio.refresh(db, as_of=AS_OF, companies=[company])

    # La divisa de cotizacion de la empresa (USD) tambien entra en la toma.
    # Llamada normal (base USD) + llamada fiscal (base EUR con USD incluida).
    assert fx_provider.calls == [
        ("USD", {"GBP", "USD"}),
        ("EUR", {"GBP", "USD"}),
    ]
    # El tipo USD fiscal es None: se salta, nunca se escribe un hueco.
    assert fx_espia.upserts == [("USD", "GBP"), ("EUR", "GBP")]
    # La posicion sin precio queda declarada como missing_market_price.
    etapa_revalor = resultado["stages"][2]
    assert etapa_revalor["status"] == "stale_data"
    assert etapa_revalor["stale_prices"] == [
        {"ticker": "AAPL", "status": "missing_market_price"}
    ]


@pytest.mark.anyio
async def test_refresh_fx_excepcion_hace_rollback_y_clasifica(db, monkeypatch):
    """El fallo en el bloque fiscal (segunda llamada al proveedor) deja el
    upsert del primer bloque pendiente: el espia sobre db.rollback demuestra
    que se llama UNA vez y que descarta esa escritura (tabla FXRate vacia).
    PortfolioFXService va REAL (escribe FXRate de verdad); solo se dobla su
    base_currency para forzar el bloque fiscal EUR."""
    company = _company(db, "AAPL")
    position = Position(
        tenant_id=db.info["tenant_id"], company_id=company.id,
        quantity=Decimal("1"), currency="GBP", base_currency="USD",
    )
    db.add(position)
    db.commit()
    provider = _FXProvider(
        rates_por_base={"USD": {"GBP": Decimal("0.79")}}
    )
    fetch_real = provider.fetch

    async def _fetch_falla_en_el_bloque_fiscal(**kwargs):
        if len(provider.calls) == 1:  # segunda llamada: bloque fiscal EUR
            provider.calls.append(
                (kwargs["base_currency"], set(kwargs["quote_currencies"]))
            )
            raise RuntimeError("ecb caido")
        return await fetch_real(**kwargs)

    provider.fetch = _fetch_falla_en_el_bloque_fiscal
    fx_real = mrs.PortfolioFXService()
    monkeypatch.setattr(fx_real, "base_currency", lambda db: "USD")
    monkeypatch.setattr(mrs, "PortfolioFXService", lambda: fx_real)
    rollbacks = []
    rollback_real = db.rollback

    def _rollback_espia():
        # La escritura del primer bloque ya esta flusheada pero SIN commit:
        # visible dentro de la transaccion (count==1) al llegar el rollback.
        rollbacks.append(db.query(FXRate).count())
        rollback_real()

    monkeypatch.setattr(db, "rollback", _rollback_espia)
    servicio = MarketRefreshService(
        price_provider=_PriceProvider(), fx_provider=provider
    )

    resultado = await servicio.refresh(db, as_of=AS_OF, companies=[company])

    assert provider.calls == [
        ("USD", {"GBP", "USD"}),
        ("EUR", {"GBP", "USD"}),
    ]
    etapa_fx = resultado["stages"][1]
    assert etapa_fx["status"] == "partial"
    assert etapa_fx["errors"] == [
        {"currency": "USD", "reason": "rate_not_available"},
        {"provider": "ECB", "reason": "RuntimeError:ecb caido"},
    ]
    # Rollback exactamente una vez, con el upsert (USD, GBP) visible en la
    # transaccion (sin commit)...
    assert rollbacks == [1]
    # ...y la escritura quedo descartada: la tabla sigue vacia.
    assert db.query(FXRate).count() == 0


@pytest.mark.anyio
async def test_refresh_posicion_en_valuation_hold_se_declara(db, monkeypatch):
    company = _company(db, "AAPL")
    db.add(MarketPrice(
        company_id=company.id, date=AS_OF, open=1, high=1, low=1,
        close=Decimal("100"), volume=100, source="FMP", quote_currency="USD",
    ))
    position = Position(
        tenant_id=db.info["tenant_id"], company_id=company.id,
        quantity=Decimal("1"), currency="USD", base_currency="EUR",
        valuation_hold_reason="split sin precio post-split verificado",
    )
    db.add(position)
    db.commit()
    servicio, _, _ = _servicio(monkeypatch)

    resultado = await servicio.refresh(db, as_of=AS_OF, companies=[company])

    etapa_revalor = resultado["stages"][2]
    assert {
        "ticker": "AAPL",
        "status": "valuation_hold",
        "reason": "split sin precio post-split verificado",
    } in etapa_revalor["stale_prices"]
    assert etapa_revalor["updated"] == 0


@pytest.mark.anyio
async def test_refresh_base_usd_divisa_oficial_tambien_en_bloque_fiscal(db, monkeypatch):
    # Posicion en GEL (divisa que el BCE no publica): los tipos oficiales se
    # piden en la toma normal Y en la fiscal (linea 637).
    company = _company(db, "AAPL")
    position = Position(
        tenant_id=db.info["tenant_id"], company_id=company.id,
        quantity=Decimal("1"), currency="GEL", base_currency="USD",
    )
    db.add(position)
    db.commit()
    oficiales = []

    async def _sin_quotes(currencies, on, **kwargs):
        oficiales.append(set(currencies))
        return {}, []

    monkeypatch.setattr(mrs, "fetch_official_quotes", _sin_quotes)
    monkeypatch.setattr(mrs, "to_base_rates", lambda *a, **k: {})
    servicio, _, fx_provider = _servicio(monkeypatch, fx_base="USD")

    await servicio.refresh(db, as_of=AS_OF, companies=[company])

    assert fx_provider.calls == [
        ("USD", {"GEL", "USD"}),
        ("EUR", {"GEL", "USD"}),
    ]
    assert oficiales == [{"GEL"}, {"GEL"}]


@pytest.mark.anyio
async def test_refresh_saved_screen_exito_entra_en_resultados(db, monkeypatch):
    screen = SavedScreen(
        tenant_id=db.info["tenant_id"], name="value", criteria=[], active=True,
    )
    db.add(screen)
    db.commit()
    monkeypatch.setattr(
        mrs, "ScreenerService",
        lambda: SimpleNamespace(
            run_saved=lambda db, s: {
                "match_count": 3, "new_match_company_ids": [42]
            }
        ),
    )
    servicio, _, _ = _servicio(monkeypatch)

    resultado = await servicio.refresh(db, as_of=AS_OF, companies=[])

    assert resultado["screen_results"] == [
        {
            "saved_screen_id": screen.id,
            "matches": 3,
            "new_match_company_ids": [42],
        }
    ]
    assert resultado["stages"][4]["status"] == "ok"
