import asyncio
import os
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.tenancy import tenant_filters
from app.models import Company, Document, FinancialFact
from app.services.connectors.damodaran import (
    DAMODARAN_ERP_COLUMN,
    DAMODARAN_ERP_PAGE,
    DAMODARAN_ERP_URL,
    ImpliedErp,
    implied_erp_series,
    latest_implied_erp,
)
from app.services.connectors.fred import FREDClient

# Sufijos Yahoo por bolsa (free tier): solo mercados confirmados en prod.
_YAHOO_SUFFIX_BY_EXCHANGE = {
    "BME": ".MC",
    "BOLSA DE MADRID": ".MC",
    # ASML cotiza en Euronext Amsterdam; en prod el exchange llega como
    # «EURONEXT AMSTERDAM» o con la nomenclatura historica de Finnhub
    # «NYSE EURONEXT - AMSTERDAM» (ver F156 en lib/exchangeName.ts). Yahoo
    # usa el sufijo .AS (ASML.AS); sin el, beta/market cap quedan ausentes.
    "EURONEXT AMSTERDAM": ".AS",
    "NYSE EURONEXT - AMSTERDAM": ".AS",
}

# Country risk premium por pais de la compania, tabla publicada y gratuita de
# Damodaran (NYU Stern), «Country Default Spreads and Risk Premiums»,
# actualizada el 5 de enero de 2026 (vintage declarado en el documento
# fuente). Solo paises verificados en esa tabla; el resto cae al ajuste
# estatico settings.wacc_country_risk_premium. US se excluye a proposito: la
# prima de mercado madura de Damodaran ya incorpora el spread soberano USA,
# sumar su CRP (0,23%) lo contaria dos veces.
_DAMODARAN_CRP_SOURCE_URL = (
    "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ctryprem.html"
)
_DAMODARAN_CRP_VINTAGE = "2026-01-05"
_DAMODARAN_CRP_BY_COUNTRY: dict[str, Decimal] = {
    "DE": Decimal("0.0"),
    "ES": Decimal("0.0155"),
    "FR": Decimal("0.0078"),
    "GB": Decimal("0.0078"),
    "IT": Decimal("0.0246"),
    "MX": Decimal("0.0246"),
    "NL": Decimal("0.0"),
    "PT": Decimal("0.0155"),
}


class WaccInputService:
    """Refresh dated, sourced market assumptions used by WACC_STANDARD_V1."""

    async def refresh(self, db: Session, company: Company) -> dict:
        settings = get_settings()
        as_of = datetime.now(UTC).date().isoformat()
        facts: list[FinancialFact] = []
        sources: list[int] = []

        fred = FREDClient()
        # La tasa libre de riesgo es la del bono benchmark de la DIVISA de
        # los flujos: DGS10 (Tesoro EE.UU.) para USD y el Bund aleman
        # (IRLTLT01DEM156N, via OCDE en FRED) para EUR - convencion
        # Damodaran: el bono aleman es el activo sin riesgo de default del
        # euro; el riesgo pais va aparte en country_risk_premium. Para otra
        # divisa no se inventa un proxy: no se genera el hecho y el motor
        # WACC lo reporta como input ausente (missing_inputs).
        company_currency = (company.currency or "USD").upper()
        series_by_currency = {
            "USD": getattr(settings, "wacc_risk_free_series", "DGS10"),
            "EUR": getattr(
                settings, "wacc_risk_free_series_eur", "IRLTLT01DEM156N"
            ),
        }
        risk_free_series = series_by_currency.get(company_currency)
        risk_free_supported = risk_free_series is not None
        # Sin clave FRED se usa fredgraph.csv (publico, fuente declarada):
        # el dato es el mismo, la via queda en el documento fuente.
        if not risk_free_supported:
            payload = {"observations": []}
        elif fred.configured():
            payload = await fred.series(risk_free_series, limit=10)
        else:
            payload = await fred.series_csv(risk_free_series, limit=10)
        observation = next(
            (
                item
                for item in payload.get("observations", [])
                if item.get("value") not in {None, "."}
            ),
            None,
        )
        if observation:
            risk_free_date = str(observation.get("date") or as_of)
            risk_free = self._decimal(observation.get("value"))
            if risk_free is not None:
                risk_free /= Decimal("100")
                document = self._source_document(
                    db,
                    company,
                    source_type="FRED",
                    title=f"FRED {risk_free_series} {risk_free_date}",
                    metadata={
                        "series": risk_free_series,
                        "date": risk_free_date,
                        # Divisa de la SERIE (= la de los flujos), no la del
                        # emisor cuando difiere.
                        "currency": company_currency,
                        "via": "api_key" if fred.configured() else "fredgraph_csv",
                    },
                )
                sources.append(document.id)
                facts.append(
                    self._upsert_fact(
                        db,
                        company,
                        metric="risk_free_rate",
                        value=risk_free,
                        period=risk_free_date,
                        source=document,
                        source_type="FRED",
                        confidence=Decimal("0.98"),
                    )
                )

        # ERP implicito del mes vigente (Damodaran, gratuito y citado). Sin
        # dato se mantiene el valor fijo de settings y se declara la fuente.
        implied_erp = await self._damodaran_implied_erp(as_of)
        country = self._company_country(company)
        crp_table_value = _DAMODARAN_CRP_BY_COUNTRY.get(country or "")
        crp_source = "damodaran_ctryprem" if crp_table_value is not None else "settings_default"
        policy_metadata = {
            "methodology": "WACC_POLICY_V1",
            "date": as_of,
            "currency": company.currency,
            "country": country
            or getattr(settings, "wacc_default_country", "US"),
            "country_risk_premium_source": crp_source,
            "equity_risk_premium_source": "damodaran_implied_erp"
            if implied_erp is not None
            else "settings_default",
        }
        if crp_table_value is not None:
            policy_metadata["country_risk_premium_reference"] = {
                "source_url": _DAMODARAN_CRP_SOURCE_URL,
                "vintage": _DAMODARAN_CRP_VINTAGE,
            }
        policy_document = self._source_document(
            db,
            company,
            source_type="wacc_policy",
            title=f"WACC policy assumptions {as_of}",
            metadata=policy_metadata,
        )
        sources.append(policy_document.id)
        if implied_erp is not None:
            erp_document = self._source_document(
                db,
                company,
                source_type="damodaran",
                title=f"Damodaran (NYU Stern) ERP implícito {implied_erp.month.isoformat()}",
                metadata={
                    "source": "Aswath Damodaran, Implied Equity Risk Premiums (NYU Stern)",
                    "source_url": DAMODARAN_ERP_URL,
                    "page": DAMODARAN_ERP_PAGE,
                    "month": implied_erp.month.isoformat(),
                    "column": DAMODARAN_ERP_COLUMN,
                    # Referencia: la columna T12m (no se usa en el WACC).
                    "erp_t12m_reference": str(implied_erp.erp_t12m)
                    if implied_erp.erp_t12m is not None
                    else None,
                    "tbond_rate": str(implied_erp.tbond) if implied_erp.tbond is not None else None,
                    "date": as_of,
                },
            )
            sources.append(erp_document.id)
            facts.append(
                self._upsert_fact(
                    db,
                    company,
                    metric="equity_risk_premium",
                    value=implied_erp.erp,
                    period=as_of,
                    source=erp_document,
                    source_type="wacc_policy",
                    confidence=Decimal("0.80"),
                )
            )
        policy_premiums: list[tuple[str, Decimal]] = []
        if implied_erp is None:
            policy_premiums.append(
                (
                    "equity_risk_premium",
                    Decimal(str(getattr(settings, "wacc_equity_risk_premium", 0.0433))),
                )
            )
        for metric, value in [
            *policy_premiums,
            (
                "country_risk_premium",
                crp_table_value
                if crp_table_value is not None
                else Decimal(
                    str(
                        getattr(
                            settings,
                            "wacc_country_risk_premium",
                            0.0,
                        )
                    )
                ),
            ),
        ]:
            facts.append(
                self._upsert_fact(
                    db,
                    company,
                    metric=metric,
                    value=value,
                    period=as_of,
                    source=policy_document,
                    source_type="wacc_policy",
                    confidence=Decimal("0.70"),
                )
            )
        # Beta y market cap: yfinance (fuente declarada, confianza menor).
        # Si Yahoo no tiene el ticker, los inputs quedan honestamente
        # ausentes y se reportan en "missing".
        market = await self._yfinance_market_inputs(self._yahoo_symbol(company))
        if market:
            market_document = self._source_document(
                db,
                company,
                source_type="yfinance",
                title=f"Yahoo Finance market inputs {as_of}",
                metadata={
                    "source": "yfinance Ticker.info",
                    "date": as_of,
                    "ticker": company.ticker,
                    "yahoo_symbol": self._yahoo_symbol(company),
                    "fields": sorted(market.keys()),
                },
            )
            sources.append(market_document.id)
            for metric, value in market.items():
                unit = "decimal" if metric == "beta" else (company.currency or "USD")
                facts.append(
                    self._upsert_fact(
                        db,
                        company,
                        metric=metric,
                        value=value,
                        period=as_of,
                        source=market_document,
                        source_type="yfinance",
                        confidence=Decimal("0.75"),
                        unit=unit,
                    )
                )
        db.commit()
        return {
            "status": "refreshed",
            "ticker": company.ticker,
            "as_of": as_of,
            "currency": company.currency,
            "risk_free_unavailable_for_currency": (
                None if risk_free_supported else company_currency
            ),
            "fact_ids": [fact.id for fact in facts],
            "source_document_ids": sorted(set(sources)),
            "missing": [
                metric
                for metric in ["risk_free_rate", "beta", "market_cap"]
                if db.scalar(
                    select(FinancialFact.id)
                    .where(
                        FinancialFact.company_id == company.id,
                        FinancialFact.metric == metric,
                        *tenant_filters(db, FinancialFact),
                    )
                    .limit(1)
                )
                is None
            ],
        }

    async def _damodaran_implied_erp(self, as_of: str) -> ImpliedErp | None:
        """ERP implicito de Damodaran del ultimo mes publicado (``None`` si no hay).

        ``WACC_DAMODARAN_ERP=0`` lo apaga sin desplegar (vuelve el valor fijo
        de settings). Nunca lanza: un fallo de red o de formato es ``None``.
        """
        if os.getenv("WACC_DAMODARAN_ERP", "1").strip() == "0":
            return None
        try:
            rows = await implied_erp_series()
            return latest_implied_erp(rows, date.fromisoformat(as_of))
        except Exception:  # noqa: BLE001 - mejor esfuerzo: el WACC sigue con settings
            return None

    def _source_document(
        self,
        db: Session,
        company: Company,
        *,
        source_type: str,
        title: str,
        metadata: dict,
    ) -> Document:
        document = db.scalar(
            select(Document).where(
                Document.company_id == company.id,
                Document.source_type == source_type,
                Document.title == title,
            )
        )
        if document is None:
            document = Document(
                company_id=company.id,
                title=title,
                source_type=source_type,
                published_at=datetime.now(UTC),
                metadata_=metadata,
            )
            db.add(document)
            db.flush()
        return document

    def _upsert_fact(
        self,
        db: Session,
        company: Company,
        *,
        metric: str,
        value: Decimal,
        period: str,
        source: Document,
        source_type: str,
        confidence: Decimal,
        unit: str = "decimal",
    ) -> FinancialFact:
        fact = db.scalar(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric == metric,
                FinancialFact.period == period,
                FinancialFact.source_type == source_type,
            )
        )
        if fact is None:
            fact = FinancialFact(
                company_id=company.id,
                metric=metric,
                value=value,
                unit=unit,
                period=period,
                source_id=source.id,
                source_type=source_type,
                is_reported=True,
                is_adjusted=False,
                confidence=confidence,
            )
            db.add(fact)
            db.flush()
        else:
            fact.value = value
            # A refreshed observation replaces its unit too. Legacy monetary
            # facts were stored as decimal; retaining that unit displays x100%.
            fact.unit = unit
            fact.source_id = source.id
            fact.confidence = confidence
        return fact

    @staticmethod
    def _company_country(company: Company) -> str | None:
        """Pais de la compania como codigo ISO-2: domicile_country y, si
        falta, el prefijo del ISIN (dos letras del pais emisor)."""
        country = (getattr(company, "domicile_country", None) or "").strip().upper()
        if country:
            return country
        isin = (getattr(company, "isin", None) or "").strip().upper()
        if len(isin) >= 2 and isin[:2].isalpha():
            return isin[:2]
        return None

    @staticmethod
    def _yahoo_symbol(company: Company) -> str:
        """Simbolo Yahoo para la empresa: las bolsas espanolas cotizan con
        sufijo (TEF.MC); sin el, Yahoo devuelve 404 y beta/market cap
        quedarian siempre ausentes. El simbolo usado queda declarado en el
        documento fuente."""
        exchange = (company.exchange or "").strip().upper()
        suffix = _YAHOO_SUFFIX_BY_EXCHANGE.get(exchange)
        if suffix and not company.ticker.upper().endswith(suffix):
            return f"{company.ticker}{suffix}"
        return company.ticker

    async def _yfinance_market_inputs(self, ticker: str) -> dict[str, Decimal]:
        """Beta y marketCap desde Yahoo Finance; {} si no hay datos."""

        def _fetch() -> dict[str, Decimal]:
            try:
                import yfinance as yf
            except ImportError:
                return {}
            try:
                info = yf.Ticker(ticker).info or {}
            except Exception:  # noqa: BLE001 - Yahoo falla de muchas formas
                return {}
            result: dict[str, Decimal] = {}
            beta = self._decimal(info.get("beta"))
            if beta is not None and beta > 0:
                result["beta"] = beta
            market_cap = self._decimal(info.get("marketCap"))
            if market_cap is not None and market_cap > 0:
                result["market_cap"] = market_cap
            return result

        return await asyncio.to_thread(_fetch)

    def _decimal(self, value) -> Decimal | None:
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
