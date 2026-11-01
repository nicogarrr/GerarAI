"""PR-4: outbox durable de alertas insider.

Evalua las transacciones Form 4 YA PERSISTIDAS (#82) y crea alertas
ResearchAlert deduplicadas. La clave de alerta es
`rule_version + regla + fingerprint de transaccion` — nunca el ticker — asi
una re-evaluacion (o una enmienda 4/A, que llega con fingerprints propios)
no duplica ni pierde alertas.

Reglas por defecto (rule_version="insider-v1"):
- big_buy: compra codigo P no derivada con valor >= 1M USD.
- c_suite_buy: compra codigo P de CEO/CFO (rol o titulo).
- cluster_buy: >=3 insiders distintos (por CIK) comprando codigo P el
  mismo ticker en una ventana de 30 dias.

Una compra sin cifra (Form 4 parseado sin valor) NO genera alerta: sin
importe no hay umbral que aplicar ni frase que interpolar, asi que la
transaccion se salta y el hueco se declara en las stats
(`skipped_missing_value`) en vez de aparecer como "compro $0". En un
cluster, una compra sin cifra no suma (seria un 0 disfrazado): el total se
publica como minimo conocido y el hueco se declara en el metadata de la
alerta y en `partial_cluster_totals`.

Solo entran transacciones codigo P adquiridas NO derivadas: grants (A),
retenciones (F), regalos (G), ejercicios (M) y disclosures 10b5-1 quedan
fuera por construccion. El wording nunca afirma "mercado abierto": el
codigo P cubre compras abiertas Y privadas (#81).

Telegram requiere suscripción persistida por propietario/tipo y jamas rompe la
evaluacion; el canal por defecto es in-app.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import generation_language
from app.models.entities import InsiderTransaction, ResearchAlert
from app.services.company_resolver import resolve_company
from app.services.insider_service import (
    BIG_BUY_THRESHOLD_USD,
    CLUSTER_MIN_INSIDERS,
    CLUSTER_WINDOW_DAYS,
    _is_c_suite,
    _parse_date,
)

RULE_VERSION = "insider-v1"
# Una compra solo avisa mientras es reciente. Sin esta ventana, un backfill o
# una re-evaluacion convertia compras de 2015 o de hace meses en alertas
# "nuevas" (161 abiertas en prod, 155 con mas de 30 dias). Misma ventana que
# el cluster. None desactiva el filtro (tests).
ALERT_MAX_AGE_DAYS: int | None = CLUSTER_WINDOW_DAYS
ALERT_TYPE_PREFIX = "insider_"


def _alert_fingerprint(rule: str, tx_fingerprint: str) -> str:
    raw = f"{RULE_VERSION}|{rule}|{tx_fingerprint}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _tx_as_signal_dict(tx: InsiderTransaction) -> dict:
    return {
        "ticker": tx.issuer_ticker,
        "insider": tx.insider,
        "role": tx.role,
        "officer_title": tx.officer_title,
        "date": tx.tx_date,
        "shares": tx.shares,
        "price": tx.price,
        "value": tx.value,
        "type": tx.code,
        "acquired_disposed": tx.acquired_disposed,
        "is_derivative": tx.is_derivative,
        "source_url": tx.source_url,
        "multi_reporter": tx.multi_reporter,
    }


def _candidate_purchases(
    db: Session, tenant_id: int | None, today: date | None = None
) -> list[InsiderTransaction]:
    rows = db.scalars(
        select(InsiderTransaction).where(
            InsiderTransaction.tenant_id.is_(tenant_id) if tenant_id is None
            else InsiderTransaction.tenant_id == tenant_id,
            InsiderTransaction.code == "P",
            InsiderTransaction.acquired_disposed == "A",
            InsiderTransaction.is_derivative.is_(False),
        )
    ).all()
    if ALERT_MAX_AGE_DAYS is not None:
        cutoff = (today or datetime.now(UTC).date()) - timedelta(days=ALERT_MAX_AGE_DAYS)
        # Fecha ilegible = no se puede afirmar que sea reciente: no avisa.
        rows = [r for r in rows if (d := _parse_date(r.tx_date)) is not None and d >= cutoff]
    return list(rows)


def _company_id_for(db: Session, ticker: str | None) -> int | None:
    if not ticker:
        return None
    company = resolve_company(db, ticker)
    return company.id if company else None


_MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def _es_num(value: float, decimals: int = 0) -> str:
    """Numero en formato en-US (miles con coma, decimales con punto).

    Decision de Nico: los importes en USD van siempre en-US con `$`.
    El nombre se conserva por compatibilidad con los llamadores.
    """
    return f"{value:,.{decimals}f}"


def _es_money(value: float) -> str:
    if value >= 1_000_000:
        return f"${_es_num(value / 1_000_000, 2)}M"
    return f"${_es_num(value)}"


def _es_date(raw: object, language: str = "es") -> str:
    parsed = _parse_date(raw) if raw else None
    if parsed is None:
        if raw:
            return str(raw)
        return "date not given" if language == "en" else "fecha no indicada"
    if language == "en":
        return f"{parsed.day} {_MONTHS_EN[parsed.month - 1]} {parsed.year}"
    return f"{parsed.day} {_MESES[parsed.month - 1]} {parsed.year}"


_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _purchase_phrase(group: list[InsiderTransaction], total: float, language: str = "es") -> str:
    """Frase en castellano (o ingles) para una o varias compras del mismo formulario (sin jerga de XML)."""
    if language == "en":
        return _purchase_phrase_en(group, total)
    dates = sorted({str(t.tx_date) for t in group if t.tx_date})
    when = (
        f"el {_es_date(dates[0])}" if len(dates) <= 1
        else f"entre el {_es_date(dates[0])} y el {_es_date(dates[-1])}"
    )
    if len(group) == 1:
        t = group[0]
        detail = f"{_es_num(float(t.shares))} acciones a ${_es_num(float(t.price), 2)}" if t.shares and t.price else ""
        head = f"compró acciones por {_es_money(total)}"
        head += f" ({detail})" if detail else ""
    else:
        shares = sum(float(t.shares) for t in group if t.shares)
        avg = f", precio medio ${_es_num(total / shares, 2)}" if shares else ""
        head = f"compró acciones en {len(group)} operaciones por {_es_money(total)} en total{avg}"
    return (f"{head}, {when}. Compra declarada en el Formulario 4; puede ser en mercado "
            "abierto o privada.")


def _purchase_phrase_en(group: list[InsiderTransaction], total: float) -> str:
    dates = sorted({str(t.tx_date) for t in group if t.tx_date})
    when = (
        f"on {_es_date(dates[0], 'en')}" if len(dates) <= 1
        else f"between {_es_date(dates[0], 'en')} and {_es_date(dates[-1], 'en')}"
    )
    if len(group) == 1:
        t = group[0]
        detail = f"{_es_num(float(t.shares))} shares at ${_es_num(float(t.price), 2)}" if t.shares and t.price else ""
        head = f"bought shares worth {_es_money(total)}"
        head += f" ({detail})" if detail else ""
    else:
        shares = sum(float(t.shares) for t in group if t.shares)
        avg = f", average price ${_es_num(total / shares, 2)}" if shares else ""
        head = f"bought shares in {len(group)} transactions worth {_es_money(total)} in total{avg}"
    return f"{head}, {when}. Purchase reported on Form 4; it may be on the open market or private."


def _build_alerts(
    db: Session, purchases: list[InsiderTransaction], language: str = "es"
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    en = language == "en"
    alerts: list[dict[str, Any]] = []
    coverage = {"skipped_missing_value": 0, "partial_cluster_totals": 0}
    # Una Form 4 (accession) puede traer decenas de lineas del mismo insider: una alerta
    # por (formulario, insider), no una por linea. Antes Lennar/Buffett daba 6 avisos.
    groups: dict[tuple[str, str], list[InsiderTransaction]] = {}
    for tx in purchases:
        if tx.value is None:
            # Sin cifra no hay ni umbral ni frase posible (c_suite_buy no
            # tiene gate): emitirla escribiria "compro $0" sobre un dato que
            # no existe. Se cuenta como hueco de cobertura, no se inventa.
            coverage["skipped_missing_value"] += 1
            continue
        filing = tx.accession_number or tx.source_url or tx.fingerprint
        groups.setdefault((str(filing), str(tx.insider_cik or tx.insider or "")), []).append(tx)
    for group in groups.values():
        group = sorted(group, key=lambda t: (str(t.tx_date), t.fingerprint))
        first = group[0]
        value = sum(float(t.value) for t in group)
        group_fp = hashlib.sha256("+".join(t.fingerprint for t in group).encode()).hexdigest()
        base = {
            "company_id": _company_id_for(db, first.issuer_ticker),
            "tx_fingerprint": group_fp,
            "tx_fingerprints": [t.fingerprint for t in group],
            "metadata": {
                "rule_version": RULE_VERSION,
                "accession_number": first.accession_number,
                "form": first.form,
                "insider_cik": first.insider_cik,
                "issuer_ticker": first.issuer_ticker,
                # Primer movimiento: el listado de alertas resuelve emisor/ticker por esta huella.
                "tx_fingerprint": first.fingerprint,
                "tx_fingerprints": [t.fingerprint for t in group],
                "transactions": len(group),
                "source_url": first.source_url,
                "data_quality": first.data_quality,
            },
        }
        is_c_suite = any(_is_c_suite(_tx_as_signal_dict(t)) for t in group)
        is_big = value >= BIG_BUY_THRESHOLD_USD
        if is_c_suite:
            # Una compra = una alerta: si el CEO/CFO supera el umbral de gran
            # compra, antes salian DOS tarjetas criticas del mismo Form 4
            # (INTC, Tan Lip Bu, 9.999.985 $: una big_buy y otra c_suite_buy).
            # La unica alerta es la c_suite (nombra el cargo) y hereda la
            # severidad alta de la gran compra; metadata declara el solape.
            alerts.append(
                {
                    **base,
                    "rule": "c_suite_buy",
                    "severity": "high" if is_big else "medium",
                    "title": f"{'C-suite purchase' if en else 'Compra C-suite'} — {first.issuer_ticker or '?'}",
                    "message": (
                        f"{first.insider or 'Insider'} "
                        f"({first.officer_title or first.role or ('executive' if en else 'directivo')}) "
                        f"{_purchase_phrase(group, value, language)}"
                    ),
                    "metadata": {**base["metadata"], "also_big_buy": is_big},
                }
            )
        elif is_big:
            alerts.append(
                {
                    **base,
                    "rule": "big_buy",
                    "severity": "high",
                    "title": f"{'Large insider purchase' if en else 'Compra insider grande'} — {first.issuer_ticker or '?'}",
                    "message": f"{first.insider or 'Insider'} {_purchase_phrase(group, value, language)}",
                }
            )

    # cluster_buy: por ticker, >=3 CIK distintos con compras P en 30 dias.
    by_ticker: dict[str, list[InsiderTransaction]] = {}
    for tx in purchases:
        if tx.issuer_ticker:
            by_ticker.setdefault(tx.issuer_ticker.upper(), []).append(tx)
    for ticker, txs in by_ticker.items():
        dated = sorted(
            ((d, tx) for tx in txs if (d := _parse_date(tx.tx_date)) is not None),
            key=lambda pair: pair[0],
        )
        for start in range(len(dated)):
            window = [
                tx for d, tx in dated
                if 0 <= (d - dated[start][0]).days <= CLUSTER_WINDOW_DAYS
            ]
            insiders = {tx.insider_cik or tx.insider for tx in window}
            if len(insiders) >= CLUSTER_MIN_INSIDERS:
                fp_source = "+".join(sorted(tx.fingerprint for tx in window))
                # El cluster se dispara por numero de insiders, no por dinero:
                # una compra sin cifra no lo invalida, pero su importe tampoco
                # puede sumar como 0. El total pasa a ser minimo conocido.
                values = [float(tx.value) for tx in window if tx.value is not None]
                total = sum(values)
                missing_value = len(window) - len(values)
                if missing_value:
                    coverage["partial_cluster_totals"] += 1
                total_phrase = (
                    f"${total:,.0f} total"
                    if not missing_value
                    else (
                        f"at least ${total:,.0f}: {missing_value} of "
                        f"{len(window)} purchases have no amount in the XML"
                    )
                    if en
                    else (
                        f"${total:,.0f} como minimo: {missing_value} de "
                        f"{len(window)} compras sin cifra en el XML"
                    )
                )
                alerts.append(
                    {
                        "company_id": _company_id_for(db, ticker),
                        "tx_fingerprint": hashlib.sha256(fp_source.encode()).hexdigest(),
                        "rule": "cluster_buy",
                        "severity": "high",
                        "title": f"{'Insider buying cluster' if en else 'Cluster de compras insider'} — {ticker}",
                        "message": (
                            (
                                f"{len(insiders)} different insiders bought {ticker} "
                                f"within {CLUSTER_WINDOW_DAYS} days ({total_phrase}). "
                                "Code P: open market or private."
                            )
                            if en
                            else (
                                f"{len(insiders)} insiders distintos compraron {ticker} "
                                f"en {CLUSTER_WINDOW_DAYS} dias ({total_phrase}). "
                                "Codigo P: mercado abierto o privado."
                            )
                        ),
                        "metadata": {
                            "rule_version": RULE_VERSION,
                            "insider_count": len(insiders),
                            "issuer_ticker": ticker,
                            "window_days": CLUSTER_WINDOW_DAYS,
                            "window_transactions": len(window),
                            "window_value_missing": missing_value,
                            "total_value_is_minimum": bool(missing_value),
                            "tx_fingerprints": [tx.fingerprint for tx in window],
                        },
                    }
                )
                break
    return alerts, coverage


def evaluate(
    db: Session,
    *,
    tenant_id: int | None = None,
    notifier: Callable[[dict], dict] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Evalua reglas sobre lo persistido y escribe el outbox. Nunca lanza."""
    stats: dict[str, Any] = {
        "status": "ok",
        "rule_version": RULE_VERSION,
        "candidates": 0,
        "alerts_created": 0,
        "alerts_existing": 0,
        "telegram_sent": 0,
        "errors": [],
        # Cobertura: compras sin cifra (no alerta) y clusters con total parcial.
        "skipped_missing_value": 0,
        "partial_cluster_totals": 0,
    }
    try:
        purchases = _candidate_purchases(db, tenant_id, today)
        stats["candidates"] = len(purchases)
        if not purchases:
            return stats
        existing = {
            row[0]
            for row in db.execute(
                select(ResearchAlert.fingerprint).where(
                    ResearchAlert.tenant_id.is_(tenant_id) if tenant_id is None
                    else ResearchAlert.tenant_id == tenant_id,
                    ResearchAlert.alert_type.like(f"{ALERT_TYPE_PREFIX}%"),
                )
            ).all()
        }
        # Idioma guardado del usuario (Ajustes); sin preferencia, espanol como siempre.
        alerts, coverage = _build_alerts(db, purchases, generation_language(db))
        stats.update(coverage)
        for alert in alerts:
            fp = _alert_fingerprint(alert["rule"], alert["tx_fingerprint"])
            legacy = alert.get("tx_fingerprints") or []
            if fp in existing or (
                legacy and all(_alert_fingerprint(alert["rule"], f) in existing for f in legacy)
            ):
                # Ya avisado (huella de grupo, o una alerta por linea emitida antes de agrupar).
                stats["alerts_existing"] += 1
                continue
            channels = ["in_app"]
            record = ResearchAlert(
                tenant_id=tenant_id,
                company_id=alert["company_id"],
                last_triggered_at=datetime.now(UTC),
                severity=alert["severity"],
                status="open",
                alert_type=f"{ALERT_TYPE_PREFIX}{alert['rule']}",
                title=alert["title"],
                message=alert["message"],
                fingerprint=fp,
                channels=channels,
                metadata_=alert["metadata"],
            )
            db.add(record)
            db.commit()
            existing.add(fp)
            stats["alerts_created"] += 1
            # Per-user/type consent and atomic delivery claims supersede the
            # old global INSIDER_ALERTS_ENABLED fire-and-forget path.
            try:
                from app.services.notification_service import NotificationService

                deliveries = NotificationService().dispatch(db, record)
                if deliveries.get("telegram", {}).get("status") == "delivered":
                    stats["telegram_sent"] += 1
            except Exception as exc:
                db.rollback()
                stats["errors"].append(f"telegram: {type(exc).__name__}")
        return stats
    except Exception as exc:  # noqa: BLE001 - el actor jamas recibe una excepcion
        stats["status"] = "error"
        stats["errors"].append(f"fatal: {type(exc).__name__}: {exc}")
        return stats
