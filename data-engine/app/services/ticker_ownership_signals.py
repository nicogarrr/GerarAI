"""Insider (Form 4) y 13F de un ticker, resumidos para la tesis y la ficha.

Conexion 10b del mapa de conexiones: las operaciones insider y las posiciones
13F ya estaban en la app (ficha > Propietarios, ProPicks, Cerebro), pero la
tesis no las leia. Este modulo las resume SOLO desde lo persistido (sin red,
sin escritura) y en tres formas:

- ``ownership_signals``: dict estructurado (bloques de evidencia de la tesis y
  endpoint ``/api/research/{ticker}/ownership-signals`` del panel de la ficha);
- ``ownership_markdown``: seccion del memo de la tesis;
- ``ownership_fact_lines``: hechos citables (texto, fuente) para el paquete
  de hechos del narrador.

Reglas de veracidad (las mismas que ``insider_operations``):
- Insider: solo codigos P/S (mercado abierto) y filas NO derivadas; fecha
  efectiva = coalesce(tx_date, filing_date); importe = ``value`` o, si falta,
  acciones x precio. Sin operaciones en la ventana -> ``sin_datos``, nunca una
  fila de ceros.
- 13F: cruce por CUSIP exacto de ``holders_by_ticker`` (sin identidad
  verificada no se afirma nada) y cambio frente al 13F anterior de cada gestor
  revisado. 13F es trimestral, con hasta 45 dias de retraso y solo largos.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import InsiderFiling, InsiderTransaction
from app.services.investor_overlap import holders_by_ticker
from app.services.investors import INVESTORS, Investor, _manager
from app.services.manager_holding_ingestion_service import ManagerHoldingIngestionService

logger = logging.getLogger("gerarai.ticker_ownership_signals")

INSIDER_WINDOW_DAYS = 180
CLUSTER_MIN_INSIDERS = 3
INSIDER_SOURCE = "SEC EDGAR · Form 4"
HOLDERS_SOURCE = "SEC EDGAR · Form 13F"
REVIEWED_INVESTORS: tuple[Investor, ...] = tuple(inv for inv in INVESTORS if inv.cik)

CHANGE_LABELS = {
    "new": "nueva posición",
    "increased": "aumenta",
    "decreased": "reduce",
    "unchanged": "mantiene",
    "closed": "sale",
}
# Si un gestor tiene varias clases del mismo CUSIP, manda el cambio mas fuerte.
_CHANGE_PRIORITY = ("new", "closed", "increased", "decreased", "unchanged")


def _parse_date(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _money(value: float) -> str:
    """Importe en USD con separador de miles es-ES (sin decimales)."""
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):,.0f}".replace(",", ".") + " USD"


def insider_signal(
    db: Session,
    ticker: str,
    *,
    as_of: date | None = None,
    window_days: int = INSIDER_WINDOW_DAYS,
) -> dict[str, Any]:
    """Compras y ventas de insiders en mercado abierto en los ultimos ``window_days``."""
    normalized = ticker.strip().upper()
    today = as_of or date.today()
    cutoff = today - timedelta(days=window_days)
    rows = db.execute(
        select(InsiderTransaction, InsiderFiling.filing_date)
        .join(InsiderFiling, InsiderFiling.id == InsiderTransaction.filing_id)
        .where(
            InsiderTransaction.issuer_ticker == normalized,
            InsiderTransaction.code.in_(("P", "S")),
            InsiderTransaction.is_derivative.is_(False),
        )
    ).all()
    sides: dict[str, dict[str, Any]] = {
        "P": {"trades": 0, "insiders": set(), "shares": 0.0, "value": 0.0, "planned": 0},
        "S": {"trades": 0, "insiders": set(), "shares": 0.0, "value": 0.0, "planned": 0},
    }
    last: date | None = None
    for tx, filing_date in rows:
        effective = _parse_date(tx.tx_date) or _parse_date(filing_date)
        if effective is None or effective < cutoff or effective > today:
            continue
        side = sides[str(tx.code)]
        side["trades"] += 1
        side["insiders"].add((tx.insider or tx.insider_cik or "?").strip().upper())
        # nosemgrep: gerarai-money-none-to-zero -- agregado informativo de filings/flujos (ranking/listado): una fila sin cifra no suma; no es un importe del usuario
        side["shares"] += float(tx.shares or 0.0)
        if tx.value is not None:
            side["value"] += float(tx.value)
        elif tx.shares is not None and tx.price is not None:
            side["value"] += float(tx.shares) * float(tx.price)
        side["planned"] += int(bool(tx.rule_10b5_1))
        last = effective if last is None or effective > last else last
    buys, sells = sides["P"], sides["S"]
    if buys["trades"] == 0 and sells["trades"] == 0:
        return {
            "status": "sin_datos",
            "window_days": window_days,
            "source": INSIDER_SOURCE,
            "detail": (
                f"Sin compras ni ventas de insiders en mercado abierto (Form 4) "
                f"persistidas para {normalized} en los últimos {window_days} días."
            ),
        }
    net_value = buys["value"] - sells["value"]
    cluster = len(buys["insiders"]) >= CLUSTER_MIN_INSIDERS
    if cluster:
        reading = f"Compras en grupo de insiders ({CLUSTER_MIN_INSIDERS} o más)"
    elif net_value > 0:
        reading = "Compras netas de insiders"
    elif net_value < 0:
        reading = "Ventas netas de insiders"
    else:
        reading = "Sin balance claro de insiders"
    return {
        "status": "ok",
        "window_days": window_days,
        "source": INSIDER_SOURCE,
        "buys": {
            "trades": buys["trades"],
            "insiders": len(buys["insiders"]),
            "shares": buys["shares"],
            "value": buys["value"],
        },
        "sells": {
            "trades": sells["trades"],
            "insiders": len(sells["insiders"]),
            "shares": sells["shares"],
            "value": sells["value"],
            "planned_10b5_1": sells["planned"],
        },
        "net_value": net_value,
        "cluster_buying": cluster,
        "last_date": last.isoformat() if last else None,
        "reading": reading,
    }


def _manager_changes_for_cusip(db: Session, inv: Investor, cusip: str) -> str | None:
    """Cambio del gestor en ese CUSIP frente a su 13F anterior (o None si no aplica).

    Lee solo las filas de ese CUSIP (``change_labels_for_cusip``), no la
    cartera entera del gestor: la ficha llama a esto una vez por gestor
    revisado y el diff completo superaba su presupuesto de lectura.
    """
    if inv.cik is None or _manager(db, inv) is None:
        return None
    found = set(
        ManagerHoldingIngestionService().change_labels_for_cusip(db, cik=inv.cik, cusip=cusip)
    )
    return next((change for change in _CHANGE_PRIORITY if change in found), None)


def holders_signal(db: Session, ticker: str) -> dict[str, Any]:
    """Gestores revisados que declaran el ticker en su ultimo 13F y su cambio trimestral."""
    normalized = ticker.strip().upper()
    base = holders_by_ticker(db, normalized)
    if base is None:
        return {
            "status": "sin_datos",
            "source": HOLDERS_SOURCE,
            "detail": f"{normalized} no está en el universo de empresas: sin cruce 13F.",
        }
    if base.get("status") == "sin_identificador" or not base.get("cusip"):
        return {
            "status": "sin_datos",
            "source": HOLDERS_SOURCE,
            "detail": base.get("identity_source")
            or "Sin CUSIP verificado para cruzar los 13F (emisor no estadounidense o identidad pendiente).",
        }
    if base.get("status") == "sin_datos":
        # Las carteras 13F se guardan por cuenta y el cron es semanal (lunes
        # 04:20 UTC): una cuenta nueva no tiene ninguna hasta su primera
        # sincronizacion. La ruta encola esa primera descarga (realqa-20).
        return {
            "status": "sin_datos",
            "reason": "sin_sincronizar",
            "source": HOLDERS_SOURCE,
            "detail": (
                "Aún no hay 13F sincronizados de los gestores revisados en tu cuenta. "
                "Se actualizan automáticamente cada lunes por la mañana."
            ),
        }
    cusip = str(base["cusip"])
    holders = list(base.get("holders") or [])
    held_slugs = {h.get("slug") for h in holders}
    changes = {"new": 0, "increased": 0, "decreased": 0, "closed": 0}
    by_slug: dict[str, str | None] = {}
    exited: list[str] = []
    for inv in REVIEWED_INVESTORS:
        change = _manager_changes_for_cusip(db, inv, cusip)
        by_slug[inv.slug] = change
        if change in changes:
            changes[change] += 1
        if change == "closed" and inv.slug not in held_slugs:
            exited.append(inv.name)
    report_dates = sorted({h["report_date"] for h in holders if h.get("report_date")})
    # nosemgrep: gerarai-money-none-to-zero -- agregado informativo de filings/flujos (ranking/listado): una fila sin cifra no suma; no es un importe del usuario
    total = sum(float(h.get("value_usd") or 0.0) for h in holders)
    top = [
        {
            "name": h.get("name"),
            "value_usd": h.get("value_usd"),
            "shares": h.get("shares"),
            "report_date": h.get("report_date"),
            "change": by_slug.get(str(h.get("slug"))),
        }
        for h in holders[:5]
    ]
    return {
        "status": "ok",
        "source": HOLDERS_SOURCE,
        "holders_count": len(holders),
        "managers_with_data": int(base.get("managers_with_data") or 0),
        "report_date": report_dates[-1] if report_dates else None,
        "total_value_usd": total if holders else None,
        "changes": changes,
        "top_holders": top,
        "exited": exited,
        "limitations": list(base.get("limitations") or []),
    }


def ownership_signals(db: Session, ticker: str, *, as_of: date | None = None) -> dict[str, Any]:
    """Ambos resumenes. Nunca lanza: un fallo deja ese bloque en ``pendiente``."""
    normalized = ticker.strip().upper()
    out: dict[str, Any] = {"ticker": normalized}
    for key, build in (
        ("insider", lambda: insider_signal(db, normalized, as_of=as_of)),
        ("holders", lambda: holders_signal(db, normalized)),
    ):
        try:
            out[key] = build()
        except Exception:  # noqa: BLE001 - mejor esfuerzo: la tesis no se rompe por esto
            logger.warning("ownership signal %s falló para %s", key, normalized, exc_info=True)
            out[key] = {
                "status": "pendiente",
                "detail": "No se pudo leer este bloque ahora mismo.",
            }
    return out


def _insider_line(ticker: str, insider: dict[str, Any]) -> str:
    buys, sells = insider["buys"], insider["sells"]
    planned = sells.get("planned_10b5_1") or 0
    planned_text = f" ({planned} con plan 10b5-1)" if planned else ""
    return (
        f"Insiders de {ticker} en los últimos {insider['window_days']} días (Form 4, mercado abierto): "
        f"{buys['insiders']} insiders compraron en {buys['trades']} operaciones por {_money(buys['value'])}; "
        f"{sells['insiders']} vendieron en {sells['trades']} operaciones por {_money(sells['value'])}{planned_text}. "
        f"Saldo neto {_money(insider['net_value'])}. Lectura: {insider['reading']}."
    )


def _holders_line(ticker: str, holders: dict[str, Any]) -> str:
    changes = holders.get("changes") or {}
    total = holders.get("total_value_usd")
    total_text = f" por {_money(total)}" if total else ""
    return (
        f"{holders['holders_count']} de {holders['managers_with_data']} gestores revisados declaran "
        f"{ticker} en su último 13F (periodo {holders.get('report_date') or 'sin fecha'}){total_text}. "
        f"Frente al trimestre anterior: {changes.get('new', 0)} nuevas posiciones, "
        f"{changes.get('increased', 0)} aumentan, {changes.get('decreased', 0)} reducen y "
        f"{changes.get('closed', 0)} salen."
    )


def ownership_fact_lines(signals: dict[str, Any]) -> list[tuple[str, str]]:
    """Hechos citables (texto, fuente) para el paquete del narrador; sin datos -> nada."""
    ticker = str(signals.get("ticker") or "")
    lines: list[tuple[str, str]] = []
    insider = signals.get("insider") or {}
    if insider.get("status") == "ok":
        lines.append((_insider_line(ticker, insider), f"{INSIDER_SOURCE} (operaciones persistidas)"))
    holders = signals.get("holders") or {}
    if holders.get("status") == "ok":
        lines.append((_holders_line(ticker, holders), f"{HOLDERS_SOURCE} (gestores revisados)"))
    return lines


def ownership_markdown(signals: dict[str, Any]) -> str:
    """Seccion del memo: insiders y fondos, con fuente, fecha y limites."""
    ticker = str(signals.get("ticker") or "")
    insider = signals.get("insider") or {}
    holders = signals.get("holders") or {}
    window = insider.get("window_days") or INSIDER_WINDOW_DAYS
    parts = [f"### Insiders (Form 4, últimos {window} días)"]
    if insider.get("status") == "ok":
        parts.append(_insider_line(ticker, insider))
        if insider.get("last_date"):
            parts.append(f"Última operación: {insider['last_date']}. Fuente: {INSIDER_SOURCE}.")
    else:
        parts.append(str(insider.get("detail") or "Sin datos de insiders."))
    parts.append("")
    parts.append("### Fondos (13F, gestores revisados)")
    if holders.get("status") == "ok":
        parts.append(_holders_line(ticker, holders))
        for holder in holders.get("top_holders") or []:
            change = CHANGE_LABELS.get(str(holder.get("change")), "sin comparación")
            value = holder.get("value_usd")
            value_text = f": {_money(float(value))}" if value else ""
            parts.append(f"- {holder.get('name')}{value_text} ({change})")
        if holders.get("exited"):
            parts.append(f"Salen este trimestre: {', '.join(holders['exited'])}.")
        for limitation in holders.get("limitations") or []:
            parts.append(f"_{limitation}_")
    else:
        parts.append(str(holders.get("detail") or "Sin datos 13F."))
    return "\n".join(parts)
