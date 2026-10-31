"""Suscripcion ICS (webcal) del calendario de resultados, con token publico revocable.

Modelo de amenaza: la URL es un secreto portador (256 bits). Solo se guarda su
SHA-256; el token en claro se devuelve una vez al crearlo. Revocar o regenerar
deja la URL antigua en 404 (mismo cuerpo que un token inexistente). El feed
contiene unicamente empresa, ticker, fecha, franja publicada, trimestre cerrado,
si la fuente la da por estimada y la fuente: ni cantidades, ni precios, ni el
origen cartera/watchlist. Aviso: el scope ``followed`` SI lista las empresas de
posiciones abiertas (solo su nombre y fecha de resultados), asi que revela que
se siguen; ``watchlist`` las excluye y es el valor prudente por defecto. Eventos de dia completo: nunca se
inventa una hora.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import CalendarFeedToken, Tenant
from app.services.earnings_dates_service import followed_calendar, portfolio_dividend_dates

SCOPES = ("followed", "watchlist")
TOKEN_PREFIX = "gfc_"
PAST_DAYS = 7
FUTURE_DAYS = 120
_SESSION = {"pre_market": "antes de la apertura", "after_market": "tras el cierre"}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(db: Session, scope: str) -> tuple[str, CalendarFeedToken]:
    """Revoca el token activo del tenant y crea uno nuevo. Devuelve (token en claro, fila)."""
    if scope not in SCOPES:
        raise ValueError("scope invalido")
    now = datetime.now(UTC)
    for row in db.scalars(select(CalendarFeedToken).where(CalendarFeedToken.revoked_at.is_(None))).all():
        row.revoked_at = now
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = CalendarFeedToken(token_hash=hash_token(token), scope=scope)
    db.add(row)
    db.commit()
    db.refresh(row)
    return token, row


def active_token(db: Session) -> CalendarFeedToken | None:
    return db.scalar(
        select(CalendarFeedToken)
        .where(CalendarFeedToken.revoked_at.is_(None))
        .order_by(CalendarFeedToken.created_at.desc())
    )


def revoke_tokens(db: Session) -> int:
    now = datetime.now(UTC)
    rows = db.scalars(select(CalendarFeedToken).where(CalendarFeedToken.revoked_at.is_(None))).all()
    for row in rows:
        row.revoked_at = now
    db.commit()
    return len(rows)


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
        .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    )


def _fold(line: str) -> list[str]:
    """RFC 5545: lineas de maximo 75 octetos, continuacion con espacio, sin cortar un caracter UTF-8."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return [line]
    out, current = [], b""
    limit = 75
    for ch in line:
        encoded = ch.encode("utf-8")
        if len(current) + len(encoded) > limit:
            out.append(current.decode("utf-8"))
            current, limit = b"", 74
        current += encoded
    out.append(current.decode("utf-8"))
    return [out[0], *[" " + part for part in out[1:]]]


def _stamp(value: datetime | None) -> str:
    moment = value or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


CALNAME_BY_SCOPE = {
    "watchlist": "Resultados de tu watchlist",
    "followed": "Resultados de cartera y watchlist",
}


def _alarm(title: str) -> list[str]:
    """Un único recordatorio el día antes (lo muestra el calendario donde se suscribe el feed)."""
    return ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_escape('Mañana: ' + title)}", "TRIGGER:-P1D", "END:VALARM"]


_DIVIDEND_TITLE = {"ex_dividend": "ex-dividendo", "dividend_payment": "pago de dividendo"}


def build_ics(
    calendar: dict,
    *,
    now: datetime | None = None,
    scope: str = "followed",
    min_date: date | None = None,
    dividends: list[dict] | None = None,
) -> str:
    calname = CALNAME_BY_SCOPE.get(scope, CALNAME_BY_SCOPE["followed"])
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//GerarAI//Calendario de resultados//ES",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        f"X-WR-CALNAME:{calname}", "X-WR-TIMEZONE:Europe/Madrid",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H",
    ]
    stamp = _stamp(now)
    for day in calendar["days"]:
        for event in day["events"]:
            start = date.fromisoformat(event["date"])
            # Nada anterior a hoy-7 d (Europe/Madrid), tampoco filas manuales.
            if min_date is not None and start < min_date:
                continue
            title = f"{event['company']} ({event['ticker']}): resultados"
            if event["confirmed"] is False:
                title += " (fecha estimada)"
            details = []
            if event["session"]:
                details.append(f"Franja: {_SESSION[event['session']]}")
            if event["fiscal_label"]:
                details.append(f"Trimestre cerrado: {event['fiscal_label']}")
            details.append(f"Fuente: {event['source']}")
            lines += [
                "BEGIN:VEVENT",
                f"UID:earnings-{event['ticker']}-{event['date']}@gerarai",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(start + timedelta(days=1)).strftime('%Y%m%d')}",
                f"SUMMARY:{_escape(title)}",
                f"DESCRIPTION:{_escape(chr(10).join(details))}",
                "TRANSP:TRANSPARENT",
            ]
            if event["source_url"]:
                lines.append(f"URL:{event['source_url']}")
            lines += _alarm(title)
            lines.append("END:VEVENT")
    for item in dividends or []:
        start = date.fromisoformat(item["date"])
        if min_date is not None and start < min_date:
            continue
        title = f"{item['company']} ({item['ticker']}): {_DIVIDEND_TITLE[item['kind']]}"
        details = [item["detail"]] if item.get("detail") else []
        details.append(f"Fuente: {item['source']}")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{item['kind']}-{item['ticker']}-{item['date']}@gerarai",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(start + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{_escape(title)}",
            f"DESCRIPTION:{_escape(chr(10).join(details))}",
            "TRANSP:TRANSPARENT",
            *_alarm(title),
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in _fold(line)) + "\r\n"


def feed_for_token(db: Session, token: str, *, today: date | None = None) -> str | None:
    """ICS del tenant dueño del token, o None si no existe/esta revocado. `db` sin tenant."""
    digest = hash_token(token)
    row = db.scalar(select(CalendarFeedToken).where(CalendarFeedToken.token_hash == digest))
    # Comparacion en tiempo constante del hash (defensa en profundidad).
    if row is None or not hmac.compare_digest(row.token_hash, digest) or row.revoked_at is not None:
        return None
    # Public bearer feeds must enforce the same account status gate as get_db.
    # Deny missing owners too, before recording use or loading any tenant data.
    tenant = db.get(Tenant, row.tenant_id)
    if tenant is None or tenant.status != "active":
        return None
    row.last_used_at = datetime.now(UTC)
    tenant_id, scope = row.tenant_id, row.scope
    db.commit()
    db.info["tenant_id"] = tenant_id
    today = today or datetime.now(ZoneInfo("Europe/Madrid")).date()
    calendar = followed_calendar(
        db, today - timedelta(days=PAST_DAYS), today + timedelta(days=FUTURE_DAYS), scope=scope
    )
    # Cartera: también ex-dividendo y pago guardados (el feed de solo watchlist no los lleva).
    dividends = (
        portfolio_dividend_dates(db, today - timedelta(days=PAST_DAYS), today + timedelta(days=FUTURE_DAYS))
        if scope != "watchlist"
        else []
    )
    return build_ics(calendar, scope=scope, min_date=today - timedelta(days=PAST_DAYS), dividends=dividends)
