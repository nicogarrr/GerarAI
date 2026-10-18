import asyncio
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Company, Document, FinancialFact
from app.services.connectors.fred import FREDClient

# Sufijos Yahoo por bolsa (free tier): solo mercados confirmados en prod.
_YAHOO_SUFFIX_BY_EXCHANGE = {
    "BME": ".MC",
    "BOLSA DE MADRID": ".MC",
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

        policy_document = self._source_document(
            db,
            company,
            source_type="wacc_policy",
            title=f"WACC policy assumptions {as_of}",
            metadata={
                "methodology": "WACC_POLICY_V1",
                "date": as_of,
                "currency": company.currency,
                "country": getattr(
                    settings, "wacc_default_country", "US"
                ),
            },
        )
        sources.append(policy_document.id)
        for metric, value in [
            (
                "equity_risk_premium",
                Decimal(
                    str(
                        getattr(
                            settings,
                            "wacc_equity_risk_premium",
                            0.0433,
                        )
                    )
                ),
            ),
            (
                "country_risk_premium",
                Decimal(
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
                    )
                    .limit(1)
                )
                is None
            ],
        }

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
            fact.source_id = source.id
            fact.confidence = confidence
        return fact

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
