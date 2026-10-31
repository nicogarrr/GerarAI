"""Senales insider a partir de Form 4 (SEC EDGAR, gratis).

Senales (codigo P = compra en mercado abierto O privada; el XML no
siempre lo distingue, asi que los textos nunca afirman "mercado abierto"):
- cluster_buy: >=3 insiders distintos comprando (codigo P) en 30 dias.
- c_suite_buy: el CEO/CFO compra (codigo P).
- big_buy: una compra (codigo P) supera 1M USD.

Enganche minimo con Telegram (notification_service): `maybe_notify_insider_buy`
solo actua si INSIDER_ALERTS_ENABLED=true y nunca rompe el flujo (todo
envuelto en try/except -> devuelve {"status": "skipped", ...}).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from app.core.config import get_settings
from app.core.errors import redact_secrets
from app.services.connectors import form4 as form4_connector
from app.services.provenance import Coverage, SourceKind, provenance

CLUSTER_MIN_INSIDERS = 3
CLUSTER_WINDOW_DAYS = 30
BIG_BUY_THRESHOLD_USD = 1_000_000.0

#: Timeout por fetch de filing XML (segundos). El conector usa 30 fijos;
#: aquí creamos cliente propio acotado cuando el llamante no inyecta uno.
FILING_FETCH_TIMEOUT_SECONDS = 15.0
#: TTL del XML por accession (los filings SEC son inmutables; la caché solo
#: evita re-descargas en re-evaluaciones).
FILING_XML_CACHE_TTL_SECONDS = 3600

logger = logging.getLogger(__name__)

_xml_cache: dict[str, tuple[float, str]] = {}
_xml_cache_fetched_at: dict[str, str] = {}


def _cached_filing_xml(filing: dict, client=None) -> tuple[str, str | None]:
    """XML del filing con caché TTL por accession + timeout acotado.

    Devuelve ``(xml, cached_fetched_at)``. ``cached_fetched_at`` es None en
    descarga fresca. Nunca lanza por la caché: ante cualquier duda se
    descarga de nuevo.
    """
    accession = str(filing.get("accession_number") or filing.get("document_url") or "")
    now = time.time()
    # nosemgrep: gerarai-broad-except-pass -- cache en memoria best-effort; el fetch real continua
    try:
        expires, xml_text = _xml_cache.get(accession, (0.0, ""))
        if xml_text and expires > now:
            return xml_text, _xml_cache_fetched_at.get(accession)
    except Exception:  # noqa: BLE001 — la caché nunca rompe el fetch
        pass
    owned_client = None
    try:
        if client is None:
            import httpx as _httpx

            owned_client = _httpx.Client(
                timeout=FILING_FETCH_TIMEOUT_SECONDS,
                headers=form4_connector.default_headers(),
            )
            xml_text = form4_connector.fetch_filing_xml(
                filing["document_url"], client=owned_client
            )
        else:
            xml_text = form4_connector.fetch_filing_xml(
                filing["document_url"], client=client
            )
    finally:
        if owned_client is not None:
            owned_client.close()
    # nosemgrep: gerarai-broad-except-pass -- cache en memoria best-effort; el fetch real continua
    try:
        _xml_cache[accession] = (now + FILING_XML_CACHE_TTL_SECONDS, xml_text)
        _xml_cache_fetched_at[accession] = datetime.now(UTC).isoformat()
    except Exception:  # noqa: BLE001 — best-effort
        pass
    return xml_text, None


def clear_filing_xml_cache() -> None:
    """Helper de tests: vacía la caché de filings."""
    _xml_cache.clear()
    _xml_cache_fetched_at.clear()



def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _to_float(value: Any) -> float | None:
    """Parse a numeric field that may arrive as str/None/garbage from Form 4 XML."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_c_suite(tx: dict) -> bool:
    return _is_ceo(tx) or _is_cfo(tx)


# Matched against the WHOLE title as words, never as a substring: "president"
# is a substring of "Vice President, Human Resources", so a VP of HR was
# reported as the CEO buying, and the alert named the wrong person.
_CEO_TITLE_PATTERNS = (
    r"\bchief\s+executive(\s+officer)?\b",
    r"\bceo\b",
    r"\bpresident\s+and\s+chief\s+executive\b",
    r"\bpresident\s*,?\s+chief\s+executive\b",
    r"\bchairman\s+and\s+ceo\b",
    r"\bchair\s+and\s+ceo\b",
)
_CFO_TITLE_PATTERNS = (
    r"\bchief\s+financial(\s+officer)?\b",
    r"\bcfo\b",
    r"\bvice\s+president\s+and\s+cfo\b",
    r"\bpresident\s*,?\s+chief\s+financial\s+officer\b",
)
# A title that marks the holder as NOT the top officer, and that can appear
# ALONGSIDE a real top-officer marker ("Vice President and CFO"), so the veto
# below only applies when no explicit marker is present.
_NOT_TOP_OFFICER = re.compile(r"\b(vice\s+president|vp|deputy|assistant|associate)\b")
# An explicit statement that this person IS the top officer.
_TOP_OFFICER_MARKER = re.compile(
    r"\b(chief|ceo|cfo|coo|cio|cpres|chairman|chair)\b"
)


def _title_matches(tx: dict, patterns: tuple[str, ...]) -> bool:
    title = str(tx.get("officer_title") or "").lower()
    role = str(tx.get("role") or "").lower()
    if not title and not role:
        return False
    # Only a DIRECTOR/OFFICER can be C-suite by title; a plain shareholder is
    # not promoted by the word "president" appearing anywhere.
    if role and "director" not in role and "officer" not in role:
        return False
    haystack = f"{title} {role}"
    if not any(re.search(pattern, haystack) for pattern in patterns):
        return False
    # "Vice President, Finance" also contains "president", so without this the
    # substring match would promote a VP. But "Vice President and CFO" names
    # the office explicitly and must survive.
    if _NOT_TOP_OFFICER.search(title) and not _TOP_OFFICER_MARKER.search(title):
        return False
    return True


def _is_ceo(tx: dict) -> bool:
    return _title_matches(tx, _CEO_TITLE_PATTERNS)


def _is_cfo(tx: dict) -> bool:
    return _title_matches(tx, _CFO_TITLE_PATTERNS)


def open_market_buys(transactions: list[dict]) -> list[dict]:
    """Compras por codigo P + adquirida (mercado abierto O privadas)."""
    return [tx for tx in transactions if form4_connector.is_open_market_buy(tx)]


def detect_signals(transactions: list[dict]) -> list[dict]:
    """Detecta cluster_buy, c_suite_buy y big_buy sobre transacciones Form 4."""
    buys = open_market_buys(transactions)
    signals: list[dict] = []

    for tx in buys:
        amount = _to_float(tx.get("value"))
        if amount is not None and amount > BIG_BUY_THRESHOLD_USD:
            signals.append(
                {
                    "signal": "big_buy",
                    "ticker": tx.get("ticker"),
                    "insider": tx.get("insider"),
                    "role": tx.get("role"),
                    "date": tx.get("date"),
                    "shares": tx.get("shares"),
                    "price": tx.get("price"),
                    "value": amount,
                    "accession_number": tx.get("accession_number"),
                    "tx_line": tx.get("tx_line"),
                    "source_url": tx.get("source_url"),
                    "form": tx.get("form"),
                    "multi_reporter": tx.get("multi_reporter", False),
                    "detail": (
                        f"{tx.get('insider')} compra ${amount:,.0f} "
                        f"({tx.get('shares')} acc. @ ${tx.get('price')})"
                    ),
                }
            )
        if _is_c_suite(tx):
            who = "CEO" if _is_ceo(tx) else ("CFO" if _is_cfo(tx) else "C-suite")
            signals.append(
                {
                    "signal": "c_suite_buy",
                    "ticker": tx.get("ticker"),
                    "insider": tx.get("insider"),
                    "role": tx.get("role"),
                    "officer_title": tx.get("officer_title"),
                    "date": tx.get("date"),
                    "shares": tx.get("shares"),
                    "price": tx.get("price"),
                    "value": amount,
                    "accession_number": tx.get("accession_number"),
                    "tx_line": tx.get("tx_line"),
                    "source_url": tx.get("source_url"),
                    "form": tx.get("form"),
                    "multi_reporter": tx.get("multi_reporter", False),
                    "detail": f"{who} {tx.get('insider')} compra (código P: mercado abierto o privado)",
                }
            )

    # Cluster: por ticker, >=3 insiders distintos comprando en 30 dias.
    by_ticker: dict[str, list[dict]] = {}
    for tx in buys:
        if tx.get("ticker"):
            by_ticker.setdefault(str(tx["ticker"]).upper(), []).append(tx)
    for ticker, items in by_ticker.items():
        dated = [( _parse_date(tx.get("date")), tx) for tx in items]
        dated = [(d, tx) for d, tx in dated if d is not None]
        dated.sort(key=lambda pair: pair[0])
        if len({tx.get("insider_cik") or tx.get("insider") for _, tx in dated}) < CLUSTER_MIN_INSIDERS:
            continue
        found = False
        for start in range(len(dated)):
            window = [
                tx for d, tx in dated
                if 0 <= (d - dated[start][0]).days <= CLUSTER_WINDOW_DAYS
            ]
            insiders = {tx.get("insider_cik") or tx.get("insider") for tx in window}
            if len(insiders) >= CLUSTER_MIN_INSIDERS:
                total = sum(
                    value
                    for value in (_to_float(tx.get("value")) for tx in window)
                    if value is not None
                )
                signals.append(
                    {
                        "signal": "cluster_buy",
                        "ticker": ticker,
                        "insiders": sorted(insiders),
                        "insider_count": len(insiders),
                        "window_days": CLUSTER_WINDOW_DAYS,
                        "window_start": dated[start][0].isoformat(),
                        "buy_count": len(window),
                        "total_value": total,
                        "detail": (
                            f"{len(insiders)} insiders compran {ticker} "
                            f"en {CLUSTER_WINDOW_DAYS} dias (${total:,.0f})"
                        ),
                    }
                )
                found = True
                break
        if found:
            continue

    return signals


def _persisted_filing_transactions(
    db, accession: str, tenant_id: int | None, ticker: str, filing: dict
) -> tuple[list[dict], str | None] | None:
    """Transacciones ya persistidas de un filing (Form 4/4-A son inmutables).

    Devuelve ``(transacciones, filing_date)`` o ``None`` si ese accession no
    esta persistido. Se usa SOLO cuando la lectura live del XML falla (la IP
    de salida puede estar baneada por la SEC): los datos son los mismos que
    se leyeron de EDGAR en su dia, y el resultado lo declara.
    """
    if db is None or not accession:
        return None
    try:
        from sqlalchemy import select

        from app.models.entities import InsiderFiling, InsiderTransaction

        # Sin tenant explicito se confia en el alcance de la sesion (igual que
        # la ruta /filings): la fila persistida es la misma que esa pantalla lista.
        def _tenant_filters(column) -> list:
            return [] if tenant_id is None else [column == tenant_id]

        record = db.scalar(
            select(InsiderFiling).where(
                *_tenant_filters(InsiderFiling.tenant_id),
                InsiderFiling.accession_number == accession,
            )
        )
        if record is None:
            return None
        rows = db.scalars(
            select(InsiderTransaction)
            .where(
                *_tenant_filters(InsiderTransaction.tenant_id),
                InsiderTransaction.filing_id == record.id,
            )
            .order_by(InsiderTransaction.id)
        ).all()
        transactions: list[dict] = []
        for line_index, row in enumerate(rows):
            transactions.append(
                {
                    "ticker": row.issuer_ticker or ticker,
                    "insider": row.insider,
                    "insider_cik": row.insider_cik,
                    "role": row.role,
                    "officer_title": row.officer_title,
                    "multi_reporter": bool(row.multi_reporter),
                    "attribution": row.attribution,
                    "type": row.code,
                    "acquired_disposed": row.acquired_disposed,
                    "shares": row.shares,
                    "price": row.price,
                    "value": row.value,
                    "date": row.tx_date or record.filing_date,
                    "is_derivative": bool(row.is_derivative),
                    "accession_number": accession,
                    "tx_line": line_index,
                    "filing_date": record.filing_date,
                    "source_url": row.source_url or record.source_url,
                    "form": row.form or record.form,
                    "from_persisted": True,
                }
            )
        return transactions, (str(record.filing_date) if record.filing_date else None)
    except Exception:  # noqa: BLE001 - el fallback nunca rompe la lectura
        return None


def _release_session_connection(db) -> None:
    """Devuelve al pool la conexion de la transaccion que el caller dejo abierta.

    get_db consulta el Tenant y hace yield sin cerrar esa transaccion de lectura,
    asi que la conexion seguia retenida durante las descargas de sec.gov. commit()
    (no rollback) conserva cualquier escritura pendiente del caller; la sesion y
    db.info (tenant scope) siguen siendo validos y la siguiente consulta abre una
    transaccion nueva. Best-effort: nunca rompe la lectura.
    """
    if db is None or not hasattr(db, "in_transaction"):
        return
    try:
        if db.in_transaction():
            db.commit()
    except Exception:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass


def get_signals_for_ticker(
    ticker: str,
    *,
    cik: str | None = None,
    limit: int = 20,
    client=None,
    fetcher: Callable[..., list[dict]] | None = None,
    db=None,
    tenant_id: int | None = None,
) -> dict:
    """Pipeline ticker -> filings Form 4 -> parse XML -> senales. Best-effort.

    `fetcher(accession...)` es inyectable para tests hermeticos. Cualquier
    fallo de red/parse degrada a status != ok con signals=[] (nunca excepcion).
    """
    wanted = ticker.strip().upper()
    try:
        _release_session_connection(db)
        resolved_cik = cik or _cik_for_ticker(wanted, client)
        if not resolved_cik:
            return {"ticker": wanted, "status": "unavailable",
                    "reason": "not a US SEC filer", "signals": []}
        filings = form4_connector.recent_form4_filings(
            resolved_cik, limit=limit, client=client
        )
        transactions: list[dict] = []
        errors: list[str] = []
        persist_errors: list[str] = []
        failure_reasons: list[str] = []
        persisted_dates: list[str] = []
        persisted_count = 0
        # Fase 1: SOLO red y parseo, sin tocar la sesion de BD. Antes cada filing
        # se persistia justo despues de descargarse, asi que la primera escritura
        # abria una transaccion que seguia retenida (conexion del pool fuera,
        # "idle in transaction") durante las descargas lentas de EDGAR de los
        # demas filings. Con varias peticiones a la vez eso agotaba el pool (5+10)
        # y todo el backend devolvia 503.
        fetched: list[tuple[dict, str | None, dict | None, Exception | None]] = []
        for filing in filings[:limit]:
            try:
                if fetcher is not None:
                    xml_text = fetcher(filing)
                else:
                    xml_text, _cached_at = _cached_filing_xml(filing, client=client)
                parsed = form4_connector.parse_form4_xml(xml_text)
                fetched.append((filing, xml_text, parsed, None))
            except Exception as exc:  # noqa: BLE001 - best-effort por filing
                fetched.append((filing, None, None, exc))
        # Fase 2: BD (persistencia y copia persistida), sin red.
        for filing, xml_text, parsed, fetch_exc in fetched:
            try:
                if fetch_exc is not None:
                    raise fetch_exc
                if parsed is None or xml_text is None:
                    raise ValueError("filing sin contenido")
                if db is not None:
                    # Persistencia durable idempotente (PR-2). Nunca rompe la lectura.
                    try:
                        from app.services import insider_persistence

                        insider_persistence.persist_filing(
                            db, filing, parsed, xml_text=xml_text, tenant_id=tenant_id
                        )
                    except Exception as persist_exc:  # noqa: BLE001
                        # Un fallo de ESCRITURA no es un fallo de lectura. Sin el
                        # rollback la sesion queda en PendingRollback y ninguna
                        # fila posterior se guarda; ademas el fallo se contaba
                        # como parseo y el resultado decia "0 de N leidos"
                        # aunque todas las senales se hubieran leido.
                        try:
                            db.rollback()
                        except Exception:  # noqa: BLE001 - la lectura sigue
                            pass
                        persist_errors.append(
                            f"{filing.get('accession_number')}: persist "
                            f"{type(persist_exc).__name__}"
                        )
                        logger.warning(
                            "insider persist %s failed: %s",
                            filing.get("accession_number"),
                            redact_secrets(str(persist_exc))[:200],
                        )
                for line_index, tx in enumerate(parsed.get("transactions", [])):
                    tx.setdefault("ticker", wanted)
                    tx["accession_number"] = filing.get("accession_number")
                    # Ordinal de fila dentro del filing: dos lotes del mismo
                    # insider en la misma fecha y el mismo fichero son dos
                    # transacciones distintas y su identidad debe distinguirlas.
                    tx["tx_line"] = line_index
                    tx["filing_date"] = filing.get("filing_date")
                    tx["source_url"] = filing.get("document_url")
                    tx["form"] = filing.get("form")
                    if not tx.get("date"):
                        tx["date"] = filing.get("filing_date")
                transactions.extend(parsed.get("transactions", []))
            except Exception as exc:  # noqa: BLE001 — best-effort por filing
                # Lectura live fallida: si el filing ya esta persistido (inmutable)
                # se usa esa copia y se declara; solo sin copia es un error.
                fallback = _persisted_filing_transactions(
                    db, str(filing.get("accession_number") or ""), tenant_id, wanted, filing
                )
                if fallback is not None:
                    persisted_txs, persisted_filing_date = fallback
                    transactions.extend(persisted_txs)
                    persisted_count += 1
                    if persisted_filing_date:
                        persisted_dates.append(persisted_filing_date)
                    continue
                # Detalle completo (tipo + texto redactado) al log del backend;
                # la respuesta solo lleva codigos estables (public_reason):
                # texto de excepcion al cliente = py/stack-trace-exposure (F30).
                logger.warning(
                    "insider filing %s: %s: %s",
                    filing.get("accession_number"), type(exc).__name__,
                    redact_secrets(str(exc))[:200],
                )
                errors.append(f"{filing.get('accession_number')}: {public_reason(exc)}")
                failure_reasons.append(public_reason(exc))
        signals = detect_signals(transactions)
        parse_error_count = len(errors)
        scanned = len(filings[:limit])
        parsed_ok = scanned - parse_error_count
        # `status` is what the endpoint's consumers read, and it was hardcoded
        # to "ok": with 20 filings all failing to fetch, the response said "ok"
        # with `signals: []` and `buy_count: 0`, which reads as "no insider
        # activity" when the truth is "nothing could be read". The user then
        # skips a company on a false all-clear.
        if parse_error_count and parsed_ok == 0:
            status = "degraded"
        elif parse_error_count or persist_errors:
            status = "partial"
        else:
            status = "ok"
        result: dict = {
            "ticker": wanted,
            "cik": resolved_cik,
            "status": status,
            "filings_scanned": scanned,
            "filings_parsed": parsed_ok,
            "filings_failed": parse_error_count,
            "coverage_ratio": (parsed_ok / scanned) if scanned else None,
            "buy_count": len(open_market_buys(transactions)),
            "signals": signals,
            "parse_error_count": parse_error_count,
            "fetched_at": datetime.now(UTC).isoformat(),
            "provenance": provenance(
                "SEC EDGAR",
                SourceKind.OFFICIAL,
                source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={resolved_cik}&type=4",
                coverage=Coverage.PARTIAL if errors or persist_errors else Coverage.OK,
                note=(
                    "Form 4 XML; codigo P = mercado abierto o privado. "
                    f"{parse_error_count} filing(s) con error de red/parse de "
                    f"{len(filings[:limit])} escaneados."
                ),
            ),
        }
        if status == "degraded" and failure_reasons and len(set(failure_reasons)) == 1:
            # Todos los filings fallaron por la misma causa (p. ej. 403 de la
            # SEC a la IP del servidor): se declara en vez de dejar solo el
            # recuento, que no dice por que no se pudo leer ninguno.
            result["reason"] = failure_reasons[0]
        if persisted_count:
            latest = max(persisted_dates) if persisted_dates else None
            result["filings_from_persisted"] = persisted_count
            result["latest_persisted_filing_date"] = latest
            result["source_note"] = (
                f"{persisted_count} de {scanned} filing(s) desde filings persistidos "
                f"(ultimo filing: {latest or 's/d'}); la lectura live de EDGAR fallo."
            )
            result["provenance"]["note"] = (
                str(result["provenance"].get("note") or "") + " " + result["source_note"]
            ).strip()
        if persist_errors:
            result["persist_error_count"] = len(persist_errors)
            result["persist_errors"] = persist_errors
            result["warnings"] = [
                f"{len(persist_errors)} de {scanned} filing(s) se leyeron pero no se "
                "pudieron guardar en el historico; las senales de esta respuesta "
                "incluyen la lectura en vivo."
            ]
            result["provenance"]["note"] = (
                str(result["provenance"].get("note") or "")
                + f" {len(persist_errors)} filing(s) sin persistir."
            ).strip()
        if errors:
            result["filing_errors"] = errors
            # Diagnostico al log del backend (tipo + texto ya redactado, sin
            # secretos): un 403/429 de la SEC era invisible fuera de la
            # respuesta y dificultaba distinguir bloqueo de parseo.
            logger.warning(
                "insider live scan %s: %d filing error(s), status=%s, reasons=%s: %s",
                wanted, len(errors), status, sorted(set(failure_reasons)), errors,
            )
        return result
    except Exception as exc:  # noqa: BLE001 — el endpoint nunca debe romper
        reason = public_reason(exc)
        logger.warning(
            "insider live scan %s: fallo global (%s: %s), reason=%s",
            wanted, type(exc).__name__, redact_secrets(str(exc))[:200], reason,
        )
        return {"ticker": wanted, "status": "degraded",
                "reason": reason, "signals": []}


def public_reason(exc: BaseException) -> str:
    """Codigo estable y sin datos internos para la vista: nunca el nombre de la
    excepcion ni su texto (F30). SEC veta IPs de datacenter con 403."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 403:
        return "sec_bloquea_datacenter"
    if status == 429:
        return "sec_limita_peticiones"
    return "fuente_no_disponible"


# company_tickers.json son ~2 MB y se descarga una vez por ticker resuelto.
# resolve_ciks lo llama en bucle sobre la watchlist, asi que una watchlist de 40
# tickers son 40 descargas de 2 MB a sec.gov en una pasada: ademas de lento, es
# exactamente el patron que hace que la SEC limite o banee la IP de salida
# (fair-access). El mapeo se cachea por proceso; solo se invalida al reiniciar
# el worker, y para CIK de emisores es un dato estable.
_CIK_MAP_CACHE: dict[str, str] | None = None
_CIK_MAP_TTL_SECONDS = 6 * 60 * 60
_CIK_MAP_LOADED_AT: float = 0.0


def _load_cik_map(client=None) -> dict[str, str]:
    """ticker en MAYUSCULAS -> CIK de 10 digitos, cacheado por proceso."""
    global _CIK_MAP_CACHE, _CIK_MAP_LOADED_AT
    import time

    now = time.monotonic()
    if (
        _CIK_MAP_CACHE is not None
        and now - _CIK_MAP_LOADED_AT < _CIK_MAP_TTL_SECONDS
    ):
        return _CIK_MAP_CACHE

    import httpx as _httpx

    url = "https://www.sec.gov/files/company_tickers.json"
    headers = form4_connector.default_headers()
    if client is not None:
        response = client.get(url, headers=headers)
    else:
        with _httpx.Client(timeout=30, headers=headers) as owned:
            response = owned.get(url)
    response.raise_for_status()

    mapping: dict[str, str] = {}
    for entry in response.json().values():
        if isinstance(entry, dict):
            symbol = str(entry.get("ticker", "")).upper()
            cik = entry.get("cik_str")
            if symbol and cik is not None:
                mapping.setdefault(symbol, str(cik).zfill(10))
    _CIK_MAP_CACHE = mapping
    _CIK_MAP_LOADED_AT = now
    return mapping


def _cik_for_ticker(ticker: str, client=None) -> str | None:
    """Resuelve el CIK via company_tickers.json (inyectable en tests).

    Exacto primero; si no, comparación sin separadores de clase con match
    único (BRK.B del master == BRK-B de EDGAR), nunca un CIK ambiguo.
    """
    from app.services.sec_ticker import match_cik

    return match_cik(_load_cik_map(client=client).items(), ticker)


# ---------------- Enganche minimo Telegram (nunca rompe) ----------------


def insider_buy_alert_text(ticker: str, signals: list[dict]) -> str:
    buys = [s for s in signals if s.get("signal") in {"cluster_buy", "c_suite_buy", "big_buy"}]
    lines = [f"Insider buy — {ticker.upper()}: {len(buys)} señal(es)"]
    for sig in buys[:5]:
        lines.append(f"• [{sig['signal']}] {sig.get('detail', '')}")
    return "\n".join(lines)[:4000]


def maybe_notify_insider_buy(
    ticker: str,
    signals: list[dict],
    *,
    notifier: Callable[[dict], dict] | None = None,
) -> dict:
    """Alerta Telegram 'insider buy' detras de INSIDER_ALERTS_ENABLED. Nunca lanza.

    Sin notifier inyectado usa NotificationService._dispatch_telegram con un
    payload minimo (sin DB). Si Telegram no esta configurado o el flag esta
    apagado -> {"status": "skipped", ...}.
    """
    try:
        settings = get_settings()
        if not getattr(settings, "insider_alerts_enabled", False):
            return {"status": "skipped", "reason": "insider alerts disabled"}
        buys = [s for s in signals if s.get("signal") in {"cluster_buy", "c_suite_buy", "big_buy"}]
        if not buys:
            return {"status": "skipped", "reason": "no buy signals"}
        text = insider_buy_alert_text(ticker, buys)
        payload = {
            "severity": "high",
            "title": f"Insider buy — {ticker.upper()}",
            "message": text,
            "company_id": ticker.upper(),
            "alert_id": f"insider-{ticker.upper()}",
        }
        if notifier is not None:
            return dict(notifier(payload))
        return {"status": "skipped", "reason": "Usa el outbox con suscripción y chat verificado"}
    except Exception as exc:  # noqa: BLE001 — notificar jamas rompe el flujo
        logger.warning(
            "insider notify %s fallo: %s: %s",
            ticker, type(exc).__name__, redact_secrets(str(exc))[:200],
        )
        return {"status": "skipped", "reason": public_reason(exc)}
