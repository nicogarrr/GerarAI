"""Best-effort evidence bundle assembled at thesis-generate time.

Ley: ninguna tesis sale ``insufficient_data`` si la empresa tiene filings
o precio de mercado que podamos traer. Este servicio intenta, en este
orden y cada fuente con su propio try/except:

  1. Fundamentales SEC EDGAR (companyfacts, sin API key): revenue, shares,
     assets, etc. -> FinancialFacts + Document SEC.
  2. Precio Finnhub (quote) -> MarketPrice; perfil (profile2) -> nombre
     real + market cap.
  3. Filings recientes 10-K/10-Q/8-K (EDGAR submissions) -> Documents SEC.
  4. Noticias materiales ya ingeridas (pipeline news: NewsEvent).
  5. Proximo earnings (calendario NASDAQ existente) + transcripcion
     existente (si no hay, hueco 'pendiente transcripcion').
  6. Investor-relations (IRConnector sobre company.ir_url) -> Documents IR.
  7. Tesis externas: NO se scrapean paywalls; se listan Documents con
     source_type='external_thesis' (via POST /documents/ingest-url o RSS)
     y si no hay, hueco accionable.

Nunca lanza: cada fuente degrada a ``status="pending"`` con el motivo y
un hueco accionable. Nada inventado: solo se persiste lo que devuelve
el proveedor; la ausencia queda marcada como pendiente.

Hermeticidad en tests: la red real pasa por `_await_sync`, que bajo
pytest (``PYTEST_CURRENT_TEST``) falla rapido sin salir a red. Los tests
inyectan datos sustituyendo los metodos `_fetch_*` con mocks, que no
pasan por `_await_sync` y por tanto siguen funcionando. Asi la suite
existente no se vuelve lenta ni flaky por EDGAR/NASDAQ/IR reales.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.errors import redact_secrets
from app.core.tenancy import tenant_filters
from app.models import Company, Document, FinancialFact, MarketPrice, NewsEvent, Transcript
from app.services.connectors import earnings_calendar as earnings_calendar_connector
from app.services.connectors import sec_edgar as sec_edgar_connector
from app.services.connectors.finnhub import FinnhubClient
from app.services.connectors.ir import IRConnector
from app.services.date_format import format_date_es
from app.services.fact_deletion import delete_financial_facts
from app.services.number_parsing import parse_machine_decimal as _decimal
from app.services.source_documents import get_or_create_source_document

logger = logging.getLogger(__name__)


def _sec_filing_title(form: str | None, filed: str | None) -> str:
    """Título es-ES de un filing SEC. Sin fecha reconocible se omite la
    cláusula de fecha: nunca «… el None» ni la cadena cruda."""
    label = form or "Documento"
    date_es = format_date_es(filed)
    if date_es:
        return f"{label} presentado ante la SEC el {date_es}"
    return f"{label} presentado ante la SEC"

# Metrica -> (tags us-gaap por preferencia, unidad). Nunca se suman
# tags. Gana el tag con el dato mas reciente: un tag preferido puede
# quedar congelado en el pasado (MSFT dejo de informar "Revenues" tras
# FY2010 y paso a RevenueFromContract...); a igual fecha, manda el orden
# de preferencia (F133).
SEC_EVIDENCE_TAGS: dict[str, tuple[list[str], str]] = {
    "revenue": (
        ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax", "RegulatedAndUnregulatedOperatingRevenue"],
        "USD",
    ),
    "shares_diluted": (
        ["WeightedAverageNumberOfDilutedSharesOutstanding", "CommonStockSharesOutstanding"],
        "shares",
    ),
    "total_assets": (["Assets"], "USD"),
    "net_income": (["NetIncomeLoss", "ProfitLoss"], "USD"),
    "operating_cash_flow": (["NetCashProvidedByUsedInOperatingActivities"], "USD"),
    "capital_expenditure": (
        ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
        "USD",
    ),
    # Mismos alias que la ingesta completa (SEC_METRIC_MAP). Desde ASU 2016-18
    # muchos emisores solo presentan el tag combinado con caja restringida:
    # POOL dejo de informar CashAndCashEquivalentsAtCarryingValue tras FY2018 y
    # la tesis se quedaba con la caja de 2016-2018 y «falta deuda neta». Va el
    # ultimo: a igual periodo manda la caja sin restringida.
    "cash_and_equivalents": (
        [
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsAndShortTermInvestments",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ],
        "USD",
    ),
    # Orden por alcance: el combinado (largo + corto plazo) es la deuda total;
    # LongTermDebtNoncurrent deja fuera la parte corriente (POOL FY2025:
    # 1.186,4 M frente a 1.199,5 M del total) y por eso va el ultimo.
    "total_debt": (
        ["DebtLongtermAndShorttermCombinedAmount", "LongTermDebt", "LongTermDebtNoncurrent"],
        "USD",
    ),
}

ANNUAL_FORMS = {"10-K", "20-F"}
FILING_FORMS = ("10-K", "10-Q", "8-K")
MAX_FILING_DOCUMENTS = 8
MAX_IR_DOCUMENTS = 10
MAX_NEWS_ITEMS = 5
EARNINGS_LOOKAHEAD_DAYS = 14
FETCH_TIMEOUT_S = 20.0

EXTERNAL_THESIS_HOWTO = (
    "Las tesis externas se pueden añadir desde Fuentes pegando la URL; "
    "no se scrapean paywalls."
)


def _await_sync(factory, timeout: float = FETCH_TIMEOUT_S):
    """Ejecuta una corrutina desde codigo sincrono con timeout.

    ``factory`` es un callable sin args que crea la corrutina (asi puede
    crearse en el hilo que la ejecuta). Funciona tanto sin event loop
    (caso normal del endpoint sync) como dentro de uno (hilo dedicado).

    Hermeticidad: bajo pytest la red real esta vetada (los tests usan
    mocks de `_fetch_*`, que no pasan por aqui).
    """
    if os.getenv("PYTEST_CURRENT_TEST"):
        raise RuntimeError("hermetic tests: live network disabled (mock _fetch_*)")

    async def _bounded():
        return await asyncio.wait_for(factory(), timeout)

    from app.services.async_bridge import run_from_any_context

    return run_from_any_context(_bounded())


def _log_source_failure(source: str, ticker: str | None, exc: BaseException) -> None:
    """Deja el detalle del fallo de una fuente solo en el log del servidor.

    El ``detail`` de ``_pending`` acaba en el texto de la tesis y en el memo:
    ahí va un mensaje fijo en español, nunca el nombre de la clase de
    excepción ni su texto crudo (que puede traer URLs con token).
    """
    logger.warning(
        "thesis evidence: fuente %s fallo para %s: %s",
        source,
        (ticker or "").upper(),
        redact_secrets(f"{type(exc).__name__}: {exc}")[:500],
    )


def _pending(source: str, detail: str, action: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": "pending", "source": source, "detail": detail}
    if action:
        payload["action"] = action
    return payload



def _news_dedupe_key(title: str | None, ticker: str | None) -> str:
    """Clave de la misma noticia en distintas agencias: primeras 10 palabras
    normalizadas del titular, sin el prefijo de ticker."""
    import re as _re
    import unicodedata as _ud

    text = _ud.normalize("NFKD", (title or "").lower())
    text = "".join(ch for ch in text if not _ud.combining(ch))
    words = _re.findall(r"[a-z0-9]+", text)
    if ticker and words and words[0] == ticker.lower():
        words = words[1:]
    return " ".join(words[:10])


def _dedupe_news_rows(rows: list, limit: int, ticker: str | None = None) -> list:
    """Quita duplicados (mismo titular normalizado) conservando el orden y el
    de mayor materialidad; devuelve como mucho `limit` filas."""
    seen: set[str] = set()
    out: list = []
    for row in rows:
        key = _news_dedupe_key(getattr(row, "title", None), ticker)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(row)
        if len(out) >= limit:
            break
    return out

def _filing_published_at(filed: object):
    """Fecha de presentacion (YYYY-MM-DD) como datetime UTC, o None si no es valida."""
    from datetime import datetime

    if isinstance(filed, datetime):
        return filed if filed.tzinfo else filed.replace(tzinfo=UTC)
    try:
        return datetime.strptime(str(filed)[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


class ThesisEvidenceService:
    """Reune y persiste el paquete de evidencia best-effort para una tesis."""

    # -- seansa de red (mockeables en tests) --------------------------------
    def _fetch_cik(self, ticker: str) -> str | None:
        return _await_sync(lambda: sec_edgar_connector.cik_for_ticker(ticker))

    def _fetch_company_facts(self, cik: str) -> dict[str, Any]:
        return _await_sync(lambda: sec_edgar_connector.company_facts(cik))

    def _fetch_filings(self, cik: str) -> list[dict[str, Any]]:
        return _await_sync(
            lambda: sec_edgar_connector.recent_filings(cik, forms=FILING_FORMS, limit=MAX_FILING_DOCUMENTS)
        )

    def _fetch_quote(self, ticker: str) -> dict[str, Any]:
        return _await_sync(lambda: FinnhubClient().quote(ticker))

    def _fetch_profile(self, ticker: str) -> dict[str, Any]:
        return _await_sync(lambda: FinnhubClient().profile(ticker))

    def _fetch_earnings(self) -> dict[str, Any]:
        today = date.today()
        return _await_sync(
            lambda: earnings_calendar_connector.fetch_earnings_range(
                today, today + timedelta(days=EARNINGS_LOOKAHEAD_DAYS)
            ),
            timeout=30.0,
        )

    def _fetch_ir(self, ir_url: str, ticker: str):
        return _await_sync(
            lambda: IRConnector().poll(ir_url, ticker=ticker, max_pages=2, max_items=MAX_IR_DOCUMENTS)
        )

    # -- entrada principal ---------------------------------------------------
    def collect(self, db: Session, company: Company) -> dict[str, Any]:
        """Reune evidencia, persiste lo conseguido y devuelve el bundle.

        Nunca lanza: si todo falla, cada bloque queda en pending y la tesis
        sale con el esqueleto honesto actual.
        """
        ticker = company.ticker.upper()
        bundle: dict[str, Any] = {"ticker": ticker, "sources": {}}
        cik: str | None = getattr(company, "cik", None) or None

        if not cik:
            try:
                cik = self._fetch_cik(ticker)
            except Exception as exc:  # noqa: BLE001 - best-effort
                cik = None
                _log_source_failure("SEC EDGAR ticker map", ticker, exc)
                bundle["sources"]["cik"] = _pending(
                    "SEC EDGAR ticker map", "CIK no resuelto (SEC EDGAR no respondió)."
                )
        if cik:
            bundle["sources"]["cik"] = {"status": "ok", "source": "SEC EDGAR", "cik": cik}

        bundle["sources"]["fundamentals"] = self._ingest_fundamentals_with_fallback(
            db, company, cik
        )
        bundle["sources"]["market"] = self._ingest_market(db, company)
        bundle["sources"]["filings"] = self._ingest_filings(db, company, cik)
        bundle["sources"]["news"] = self._collect_news(db, company)
        bundle["sources"]["earnings"] = self._collect_earnings(db, company)
        bundle["sources"]["transcript"] = self._collect_transcript(db, company)
        bundle["sources"]["ir"] = self._ingest_ir(db, company)
        bundle["sources"]["external_theses"] = self._collect_external_theses(db, company)
        bundle["sources"].update(self._collect_ownership(db, company))
        db.flush()
        return bundle

    def collect_stored(self, db: Session, company: Company) -> dict[str, Any]:
        """Bloques de evidencia que SOLO leen la base (sin red, sin escritura).

        La generacion de empresas seguidas (stored_evidence_only) no recolecta
        por red, pero noticias, transcripciones y tesis externas ya estan en la
        base: omitirlas dejaba la tesis sin noticias aunque existieran.
        """
        return {
            "ticker": company.ticker.upper(),
            "sources": {
                "news": self._collect_news(db, company),
                "transcript": self._collect_transcript(db, company),
                "external_theses": self._collect_external_theses(db, company),
                **self._collect_ownership(db, company),
            },
        }

    @staticmethod
    def _collect_ownership(db: Session, company: Company) -> dict[str, Any]:
        """Insider (Form 4) y fondos 13F ya persistidos: solo lectura, nunca lanza.

        Conexion 10b: la tesis lee las operaciones insider y el cambio 13F de
        los gestores revisados como dos bloques de evidencia mas.
        """
        from app.services.ticker_ownership_signals import ownership_signals

        signals = ownership_signals(db, company.ticker)
        return {"insider": signals["insider"], "holders": signals["holders"]}

    # -- 1. fundamentales: SEC y, si no aporta, fuentes alternativas ----------
    def _ingest_fundamentals_with_fallback(
        self, db: Session, company: Company, cik: str | None
    ) -> dict[str, Any]:
        """SEC primero; sin CIK o sin us-gaap, el orden de fundamentals_fallback
        (oficial guardado > Yahoo revisado, no oficial)."""
        from app.services.fundamentals_fallback import ingest_with_fallback

        return ingest_with_fallback(db, company, self._ingest_fundamentals(db, company, cik))

    def _ingest_fundamentals(
        self, db: Session, company: Company, cik: str | None
    ) -> dict[str, Any]:
        if not cik:
            return _pending(
                "SEC EDGAR companyfacts",
                "Sin CIK no hay companyfacts (empresa no filer USA o EDGAR inaccesible).",
            )
        try:
            facts_payload = self._fetch_company_facts(cik)
        except Exception as exc:  # noqa: BLE001 - best-effort
            _log_source_failure("SEC EDGAR companyfacts", company.ticker, exc)
            return _pending("SEC EDGAR companyfacts", "EDGAR inaccesible ahora mismo.")
        us_gaap = ((facts_payload or {}).get("facts") or {}).get("us-gaap") or {}
        extracted = self._extract_recent_annuals(us_gaap)
        if not extracted:
            return _pending(
                "SEC EDGAR companyfacts",
                f"CIK {cik} sin métricas us-gaap aprovechables.",
            )
        document = self._get_or_create_document(
            db,
            company,
            title=f"SEC XBRL companyfacts - {company.ticker}",
            source_type="SEC",
            source_url=(
                f"https://data.sec.gov/api/xbrl/companyfacts/CIK{str(cik).zfill(10)}.json"
            ),
        )
        # Aditivo, nunca destructivo: refresh/sec es el duenio del historico
        # SEC completo; aqui solo rellenamos el ultimo anual si falta. Antes
        # este paso borraba TODOS los facts SEC y dejaba 1 ano por metrica,
        # tirando abajo el DCF (insufficient_data) tras cada tesis.
        tenant_id = db.info.get("tenant_id")
        tenant_filter = (
            FinancialFact.tenant_id == tenant_id
            if tenant_id is not None
            else FinancialFact.tenant_id.is_(None)
        )
        existing = {
            (fact.metric, fact.period)
            for fact in db.scalars(
                select(FinancialFact).where(
                    FinancialFact.company_id == company.id,
                    FinancialFact.source_type == "SEC",
                    tenant_filter,
                )
            )
        }
        imported = 0
        skipped_existing = 0
        for metric, infos in extracted.items():
            for info in infos:
                if (metric, info["period"]) in existing:
                    skipped_existing += 1
                    continue
                value = _decimal(info["value"])
                if value is None:
                    continue
                if metric == "capital_expenditure":
                    # PaymentsToAcquire... llega en positivo; el resto de la
                    # app guarda el capex en negativo (salida de caja), como la
                    # ingesta SEC completa. En positivo, FCF = OCF + capex salia
                    # inflado en 2 x capex (TTM, modelo a largo plazo).
                    value = -abs(value)
                db.add(
                    FinancialFact(
                        company_id=company.id,
                        metric=metric,
                        value=value,
                        unit=info["unit"],
                        period=info["period"],
                        fiscal_year=info["fiscal_year"],
                        fiscal_quarter=info.get("fiscal_quarter"),
                        source_id=document.id,
                        source_type="SEC",
                        is_reported=True,
                        confidence=Decimal("0.95"),
                    )
                )
                imported += 1
        db.flush()
        if imported == 0 and skipped_existing == 0:
            return _pending("SEC EDGAR companyfacts", "Hechos sin valor numerico aprovechable.")
        return {
            "status": "ok",
            "source": "SEC EDGAR companyfacts",
            "facts_imported": imported,
            "already_present": skipped_existing,
            "metrics": sorted(extracted.keys()),
            "document_id": document.id,
        }

    # Metricas de flujo (duracion): un hecho sin ``start`` no puede
    # probar que cubre un ano, asi que no entra al pool anual. Las
    # instantaneas (balance, acciones) no llevan ``start`` por naturaleza.
    FLOW_METRICS = frozenset({"revenue", "net_income", "operating_cash_flow"})

    @classmethod
    def _is_annual_duration(cls, entry: dict[str, Any], metric: str) -> bool:
        """True si el hecho prueba duracion ~1 ano (flujos) o es
        instantaneo sin ``start``.

        Los 10-K republican trimestres: un form anual NO garantiza
        duracion anual (MSFT FY2010: revenue 16.039B con start 2010-04-01
        es el Q4, no el ano - F133). Fechas no parseables: cerrado.
        """
        start, end = entry.get("start"), entry.get("end")
        if not start:
            return metric not in cls.FLOW_METRICS
        try:
            days = (
                datetime.strptime(str(end), "%Y-%m-%d").date()
                - datetime.strptime(str(start), "%Y-%m-%d").date()
            ).days
        except (TypeError, ValueError):
            return False
        return 300 <= days <= 400

    # Serie anual reciente por metrica (por defecto 3 ejercicios): el modelo
    # a largo plazo necesita historial (p. ej. dos periodos de ingresos) y la
    # SEC lo publica aunque el ultimo 10-K ya no traiga la linea (HYMC: la
    # linea de ingresos desaparece tras FY2023, pero FY2022 sigue en
    # companyfacts). Aditivo: cada (metrica, periodo) se inserta una sola vez.
    RECENT_ANNUAL_YEARS = 3

    def _extract_recent_annuals(
        self, us_gaap: dict[str, Any], max_years: int | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Hasta ``max_years`` hechos ANUALES por metrica, del mas reciente al mas antiguo.

        Mismas reglas que ``_extract_latest_annual`` (F133): duracion anual
        probada, nunca sumar tags, preferencia declarada entre tags a igual
        periodo. Si una metrica no tiene NINGUN hecho anual, conserva el
        comportamiento anterior: un unico hecho con el fallback de
        ``_extract_latest_annual`` (ultimo trimestre), para no perder
        empresas que solo reportan trimestres.
        """
        limit = max_years or self.RECENT_ANNUAL_YEARS
        out: dict[str, list[dict[str, Any]]] = {}
        for metric, (tags, unit) in SEC_EVIDENCE_TAGS.items():
            # periodo (end) -> (preferencia de tag, filed, entry): a igual
            # periodo manda el tag preferido; a mismo tag, el envio reciente.
            by_end: dict[str, tuple[int, str, str, dict[str, Any]]] = {}
            for preference, tag in enumerate(tags):
                entries = ((us_gaap.get(tag) or {}).get("units") or {}).get(unit, [])
                for entry in entries:
                    if not isinstance(entry, dict) or entry.get("val") is None or not entry.get("end"):
                        continue
                    if str(entry.get("form", "")).upper() not in ANNUAL_FORMS:
                        continue
                    if not self._is_annual_duration(entry, metric):
                        continue
                    end = str(entry["end"])
                    filed = str(entry.get("filed", ""))
                    current = by_end.get(end)
                    if current is None or preference < current[0] or (
                        preference == current[0] and filed > current[1]
                    ):
                        by_end[end] = (preference, filed, tag, entry)
            if not by_end:
                legacy_map = self._extract_latest_annual(us_gaap)
                legacy = legacy_map.get(metric)
                if legacy is not None:
                    out[metric] = [legacy]
                continue
            infos: list[dict[str, Any]] = []
            for end in sorted(by_end.keys(), reverse=True)[:limit]:
                _, _, tag, entry = by_end[end]
                try:
                    fiscal_year = int(end[:4])
                except ValueError:
                    fiscal_year = None
                infos.append(
                    {
                        "value": entry["val"],
                        "unit": unit,
                        "period": f"{end}:FY",
                        "fiscal_year": fiscal_year,
                        "fiscal_quarter": "FY",
                        "concept": tag,
                        "form": entry.get("form"),
                    }
                )
            out[metric] = infos
        return out

    def _extract_latest_annual(self, us_gaap: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Ultimo hecho anual por metrica (fallback: ultimo trimestre).

        Reglas (F133, MSFT tenant 5):
        - la duracion del hecho, no solo el form: un trimestre republicado
          en un 10-K no es un dato anual, y las metricas de flujo sin
          ``start`` tampoco (no pueden probar duracion);
        - el fallback nunca etiqueta FY lo que no probo duracion anual;
        - entre tags gana el hecho ANUAL sobre cualquier trimestre, y
          dentro de la misma clase el de periodo cubierto mas reciente
          (end), no el de envio mas reciente (filed): una enmienda de un
          periodo antiguo no desplaza al periodo nuevo. A doble empate
          manda la preferencia declarada en SEC_EVIDENCE_TAGS; nunca se
          suman tags.
        """
        out: dict[str, dict[str, Any]] = {}
        for metric, (tags, unit) in SEC_EVIDENCE_TAGS.items():
            best: dict[str, Any] | None = None
            for tag in tags:
                entries = ((us_gaap.get(tag) or {}).get("units") or {}).get(unit, [])
                valid = [
                    e
                    for e in entries
                    if isinstance(e, dict) and e.get("val") is not None and e.get("end")
                ]
                annual = [
                    e
                    for e in valid
                    if str(e.get("form", "")).upper() in ANNUAL_FORMS
                    and self._is_annual_duration(e, metric)
                ]
                pool = annual or valid
                if not pool:
                    continue
                # Periodo cubierto primero: una enmienda (filed reciente de
                # un end antiguo) no desplaza al periodo nuevo.
                pool.sort(key=lambda e: (str(e.get("end", "")), str(e.get("filed", ""))))
                latest = pool[-1]
                end = str(latest["end"])
                try:
                    fiscal_year = int(end[:4])
                except ValueError:
                    fiscal_year = None
                is_annual = (
                    str(latest.get("form", "")).upper() in ANNUAL_FORMS
                    and self._is_annual_duration(latest, metric)
                )
                candidate = {
                    "value": latest["val"],
                    "unit": unit,
                    "period": f"{end}:FY" if is_annual else f"{end}:{latest.get('form')}",
                    "fiscal_year": fiscal_year,
                    "fiscal_quarter": "FY" if is_annual else None,
                    "concept": tag,
                    "form": latest.get("form"),
                }
                # Anual > trimestre entre tags; dentro de la clase, el
                # periodo cubierto mas reciente; doble empate -> el tag ya
                # elegido (preferencia declarada).
                key = (is_annual, end, str(latest.get("filed", "")))
                if best is None or key > best["_key"]:
                    candidate["_key"] = key
                    best = candidate
            if best is not None:
                best.pop("_key", None)
                out[metric] = best
        return out

    # -- 2. precio + perfil Finnhub -------------------------------------------
    def _ingest_market(self, db: Session, company: Company) -> dict[str, Any]:
        ticker = company.ticker.upper()
        result: dict[str, Any] = {"status": "pending", "source": "Finnhub"}
        try:
            quote = self._fetch_quote(ticker)
        except Exception as exc:  # noqa: BLE001 - best-effort
            _log_source_failure("Finnhub quote", ticker, exc)
            result["detail"] = "Cotización inaccesible ahora mismo."
            quote = None
        price = _decimal((quote or {}).get("c")) if quote else None
        # Fallar cerrado ante payload malformado: timestamp o volumen invalidos
        # no propagan una excepcion; sin fecha honesta no se escribe barra.
        try:
            timestamp = int((quote or {}).get("t") or 0) if quote else 0
            quote_date = datetime.fromtimestamp(timestamp, tz=UTC).date() if timestamp > 0 else None
        except (TypeError, ValueError, OverflowError, OSError):
            quote_date = None
        try:
            volume = int(quote["v"]) if quote and quote.get("v") is not None else None
        except (TypeError, ValueError):
            volume = None
        if price is not None and price > 0:
            if quote_date is None:
                # Sin timestamp del proveedor no hay fecha honesta: fechar la
                # quote con el dia de la ingesta fabricaba barras de fin de
                # semana con el ultimo cierre conocido.
                result["detail"] = "Quote sin timestamp valido del proveedor: no se escribe barra sin fecha honesta."
            elif quote_date > datetime.now(UTC).date():
                result["detail"] = "Quote con fecha futura rechazada."
            else:
                existing = db.scalar(
                    select(MarketPrice).where(
                        MarketPrice.company_id == company.id, MarketPrice.date == quote_date
                    )
                )
                if existing and existing.quote_currency is not None:
                    result.update({"status": "unknown_price_unit", "detail": "Quote sin unidad verificable para esta barra ajustada."})
                elif existing:
                    # Barra real ya persistida: se actualiza solo el close y se
                    # preservan OHLC y el adjusted autentico de esa fecha.
                    existing.close = price
                    if volume is not None:
                        existing.volume = volume
                    existing.source = "Finnhub"
                    existing.quote_currency = None
                else:
                    # Spot no es barra ajustada: adj_close NULL, nunca una copia
                    # de close que afirme un ajuste no realizado.
                    db.add(
                        MarketPrice(
                            company_id=company.id,
                            date=quote_date,
                            open=price,
                            high=price,
                            low=price,
                            close=price,
                            adj_close=None,
                            volume=volume,
                            source="Finnhub",
                            quote_currency=None,
                        )
                    )
                if result["status"] != "unknown_price_unit":
                    result.update({"status": "ok", "price": float(price), "price_as_of": quote_date.isoformat()})
        else:
            result["detail"] = result.get("detail") or "Quote sin precio util (c<=0 o vacio)."
        try:
            profile = self._fetch_profile(ticker)
        except Exception as exc:  # noqa: BLE001 - best-effort
            _log_source_failure("Finnhub profile", ticker, exc)
            result["profile_detail"] = "Perfil inaccesible ahora mismo."
            profile = None
        if profile:
            name = str(profile.get("name") or "").strip()
            if name and (not (company.name or "").strip() or company.name.strip().upper() == ticker):
                company.name = name
                db.add(company)
                result["name"] = name
            market_cap = _decimal(profile.get("marketCapitalization"))
            # El market cap se fecha con la sesion de la quote del proveedor,
            # nunca con el dia de la ingesta (fabricaba hechos de sabado/domingo
            # con una variacion inexistente). Sin fecha honesta no se escribe.
            cap_date = quote_date if quote_date and quote_date <= datetime.now(UTC).date() else None
            if market_cap is not None and market_cap > 0 and cap_date is not None:
                # marketCapitalization de Finnhub viene en millones de USD.
                value = market_cap * Decimal("1000000")
                period = cap_date.isoformat()
                already = db.scalar(
                    select(FinancialFact).where(
                        FinancialFact.company_id == company.id,
                        FinancialFact.metric == "market_cap",
                        FinancialFact.period == period,
                        FinancialFact.source_type == "Finnhub",
                    )
                )
                if already is None:
                    db.add(
                        FinancialFact(
                            company_id=company.id,
                            metric="market_cap",
                            value=value,
                            unit="USD",
                            period=period,
                            source_id=None,
                            source_type="Finnhub",
                            is_reported=True,
                            confidence=Decimal("0.75"),
                        )
                    )
                result["market_cap"] = float(value)
            exchange = str(profile.get("exchange") or "").strip()
            if exchange and not (company.exchange or "").strip():
                company.exchange = exchange
                db.add(company)
        db.flush()
        if result["status"] != "ok" and "market_cap" not in result and "name" not in result:
            result.setdefault("detail", "Sin precio ni perfil (sin FINNHUB_API_KEY o red).")
        return result

    # -- 3. filings como documentos -------------------------------------------
    def _ingest_filings(
        self, db: Session, company: Company, cik: str | None
    ) -> dict[str, Any]:
        if not cik:
            return _pending("SEC EDGAR submissions", "Sin CIK no hay filings.")
        try:
            filings = self._fetch_filings(cik) or []
        except Exception as exc:  # noqa: BLE001 - best-effort
            _log_source_failure("SEC EDGAR submissions", company.ticker, exc)
            return _pending("SEC EDGAR submissions", "Filings de SEC EDGAR inaccesibles ahora mismo.")
        created = 0
        items: list[dict[str, Any]] = []
        for filing in filings[:MAX_FILING_DOCUMENTS]:
            form = filing.get("form")
            url = filing.get("document_url") or filing.get("index_url")
            filed = filing.get("filing_date")
            items.append({"form": form, "filing_date": filed, "url": url})
            if not url:
                continue
            exists = db.scalar(
                select(Document.id)
                .where(
                    Document.source_url == url,
                    *tenant_filters(db, Document),
                )
                .limit(1)
            )
            if exists:
                continue
            db.add(
                Document(
                    company_id=company.id,
                    title=_sec_filing_title(form, filed),
                    source_type="SEC",
                    source_url=url,
                    # Sin published_at la UI de Fuentes (orden por fecha de
                    # publicacion) mandaba los filings nuevos al final.
                    published_at=_filing_published_at(filed),
                    metadata_={
                        "form": form,
                        "filing_date": filed,
                        "accession_number": filing.get("accession_number"),
                        "provider": "SEC EDGAR submissions",
                    },
                )
            )
            created += 1
        db.flush()
        if not items:
            return _pending("SEC EDGAR submissions", "Sin 10-K/10-Q/8-K recientes.")
        return {
            "status": "ok",
            "source": "SEC EDGAR submissions",
            "items": items,
            "documents_created": created,
        }

    # -- 4. noticias (solo lectura del pipeline news) --------------------------
    def _collect_news(self, db: Session, company: Company) -> dict[str, Any]:
        # Se leen más filas de las necesarias: una misma noticia publicada por
        # varias agencias (PR Newswire, GlobeNewswire, Morningstar) ocupaba 3 de
        # los 5 huecos de «noticias materiales» y contaba como 3 eventos.
        # Captacion de demandantes de despachos de abogados y paginas de datos
        # de precios no son noticias de la empresa: no entran en la tesis.
        from app.services.ticker_news_lane import is_data_page_headline, is_law_firm_solicitation

        candidates = [
            row
            for row in db.scalars(
                select(NewsEvent)
                .where(NewsEvent.company_id == company.id)
                .order_by(desc(NewsEvent.materiality_score), desc(NewsEvent.date))
                .limit(MAX_NEWS_ITEMS * 8)
            ).all()
            if not (
                is_law_firm_solicitation(
                    (row.metadata_ or {}).get("source_headline") or row.title, None
                )
                or is_data_page_headline((row.metadata_ or {}).get("source_headline") or row.title)
            )
        ]
        rows = _dedupe_news_rows(
            candidates,
            MAX_NEWS_ITEMS,
            company.ticker,
        )
        if not rows:
            return _pending(
                "news pipeline (NewsEvent)",
                "Sin noticias ingeridas para este ticker.",
            )
        return {
            "status": "ok",
            "source": "news pipeline (NewsEvent)",
            "items": [
                {
                    "id": r.id,
                    "title": r.title,
                    "date": r.date.isoformat() if r.date else None,
                    "source": r.source,
                    "materiality": r.materiality_score,
                    "url": r.url,
                    # Titular original publicado por el medio (si el conector lo
                    # guardo): es lo unico citable verbatim. `title` es un
                    # resumen compuesto por la app y NUNCA se presenta como
                    # titular publicado.
                    "source_headline": (r.metadata_ or {}).get("source_headline"),
                    "date_source": (r.metadata_ or {}).get("date_source"),
                    # Marca persistida en ingesta: la narrativa la usa para
                    # preguntar si hay version mas reciente del hecho.
                    "requires_update": bool(r.requires_update),
                }
                for r in rows
            ],
        }

    # -- 5a. proximo earnings ---------------------------------------------------
    def _collect_earnings(self, db: Session, company: Company) -> dict[str, Any]:
        del db  # solo red + traza; no escribe en este bloque
        try:
            payload = self._fetch_earnings() or {}
        except Exception as exc:  # noqa: BLE001 - best-effort
            _log_source_failure("NASDAQ earnings calendar", company.ticker, exc)
            return _pending(
                "NASDAQ earnings calendar",
                "Calendario de resultados inaccesible ahora mismo.",
            )
        wanted = company.ticker.upper()
        coming = sorted(
            (
                e
                for e in (payload.get("events") or [])
                if str(e.get("symbol", "")).upper() == wanted and e.get("date")
            ),
            key=lambda e: str(e.get("date")),
        )
        if not coming:
            return _pending(
                "NASDAQ earnings calendar",
                f"Sin earnings de {wanted} en los próximos {EARNINGS_LOOKAHEAD_DAYS} días.",
            )
        nxt = coming[0]
        return {
            "status": "ok",
            "source": "NASDAQ earnings calendar",
            "next_date": nxt.get("date"),
            "time": nxt.get("time"),
            "eps_forecast": nxt.get("eps_forecast"),
        }

    # -- 5b. transcripcion -------------------------------------------------------
    def _collect_transcript(self, db: Session, company: Company) -> dict[str, Any]:
        row = db.scalar(
            select(Transcript)
            .where(Transcript.company_id == company.id)
            .order_by(desc(Transcript.id))
            .limit(1)
        )
        if row is None:
            return _pending(
                "transcripts",
                "Pendiente transcripción: sin fuente gratuita disponible.",
                action="Puede añadirse manualmente desde Fuentes.",
            )
        return {
            "status": "ok",
            "source": "transcripts",
            "title": row.title,
            "period": row.period,
        }

    # -- 6. IR -------------------------------------------------------------------
    def _ingest_ir(self, db: Session, company: Company) -> dict[str, Any]:
        ir_url = (getattr(company, "ir_url", None) or "").strip()
        if not ir_url:
            return _pending(
                "IR de la empresa",
                "Sin ir_url en el master; hueco marcado.",
                action="Falta la URL de relación con inversores en la ficha de la compañía.",
            )
        try:
            result = self._fetch_ir(ir_url, company.ticker.upper())
        except Exception as exc:  # noqa: BLE001 - best-effort
            _log_source_failure("IR de la empresa", company.ticker, exc)
            return _pending(
                "IR de la empresa",
                "Web de relación con inversores inaccesible ahora mismo.",
                action="Puede añadirse manualmente desde Fuentes.",
            )
        items = getattr(result, "items", None) or []
        created = 0
        listed: list[dict[str, Any]] = []
        for item in items[:MAX_IR_DOCUMENTS]:
            listed.append({"title": item.title, "url": item.url})
            if not item.url:
                continue
            exists = db.scalar(
                select(Document.id)
                .where(
                    Document.source_url == item.url,
                    *tenant_filters(db, Document),
                )
                .limit(1)
            )
            if exists:
                continue
            db.add(
                Document(
                    company_id=company.id,
                    title=item.title or f"IR release - {company.ticker}",
                    source_type="IR",
                    source_url=item.url,
                    metadata_={"provider": "company IR", "ir_url": ir_url},
                )
            )
            created += 1
        db.flush()
        errors = getattr(result, "errors", None) or []
        if not listed:
            return _pending(
                "IR de la empresa",
                f"IR sin releases detectados ({'; '.join(errors)[:200]}).",
                action="Puede añadirse manualmente desde Fuentes.",
            )
        return {
            "status": "ok",
            "source": f"company IR ({ir_url})",
            "items": listed,
            "documents_created": created,
        }

    # -- 7. tesis externas (sin paywalls) -----------------------------------------
    def _collect_external_theses(self, db: Session, company: Company) -> dict[str, Any]:
        rows = list(
            db.scalars(
                select(Document)
                .where(
                    Document.company_id == company.id,
                    Document.source_type == "external_thesis",
                )
                .order_by(desc(Document.id))
                .limit(10)
            ).all()
        )
        if not rows:
            return _pending(
                "tesis externas",
                "Sin tesis de terceros (no se scrapean paywalls).",
                action=EXTERNAL_THESIS_HOWTO,
            )
        return {
            "status": "ok",
            "source": "tesis externas (pegadas por el usuario)",
            "items": [{"title": r.title, "url": r.source_url} for r in rows],
        }

    # -- helpers de persistencia ---------------------------------------------------
    def _get_or_create_document(
        self, db: Session, company: Company, *, title: str, source_type: str, source_url: str
    ) -> Document:
        return get_or_create_source_document(
            db,
            company,
            title=title,
            source_type=source_type,
            source_url=source_url,
            metadata={"provider": source_type, "auto_ingested": True},
        )

    def _replace_facts(self, db: Session, company: Company, source_type: str) -> None:
        tenant_id = db.info.get("tenant_id")
        tenant_filter = (
            FinancialFact.tenant_id == tenant_id
            if tenant_id is not None
            else FinancialFact.tenant_id.is_(None)
        )
        # delete_financial_facts desvincula las referencias entrantes (FK NO
        # ACTION en Postgres) y respeta los hechos con correccion humana.
        delete_financial_facts(
            db,
            FinancialFact.company_id == company.id,
            FinancialFact.source_type == source_type,
            tenant_filter,
        )
        db.flush()
