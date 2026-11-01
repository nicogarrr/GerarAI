"""Textos de los avisos de proximos resultados (titulo, mensaje, correo), en espanol o ingles.

Modulo puro: recibe el diccionario ``earnings`` que ``earnings_reminders``
guarda en ``ResearchAlert.metadata_["earnings"]`` y devuelve texto. Misma
filosofia que ``dca_alert_copy``: solo se muestra lo que existe (una franja o
trimestre ausentes no se pintan) y la fecha nunca se adorna con una hora que
la fuente no publico. ``language`` ("es" por defecto) es el idioma guardado
del usuario al disparar el aviso; el espanol no cambia.
"""

from __future__ import annotations

from html import escape
from typing import Any

from app.services.dca_alert_copy import short_date
from app.services.display_es import fecha_es
from app.services.email_delivery import EmailContent

DISCLAIMER = "Aviso de calendario de resultados; no es asesoramiento financiero."

WINDOWS = ("today", "day", "week")
SESSION_LABELS = {"pre_market": "antes de la apertura", "after_market": "tras el cierre"}
ORIGIN_LABELS = {"cartera": "cartera", "watchlist": "watchlist"}

DISCLAIMER_EN = "Earnings calendar notice; not financial advice."
SESSION_LABELS_EN = {"pre_market": "before the open", "after_market": "after the close"}
ORIGIN_LABELS_EN = {"cartera": "portfolio", "watchlist": "watchlist"}
FOOTER = "La fecha procede del calendario de resultados de GerarAI, con su fuente y estado."
FOOTER_EN = "The date comes from GerarAI's earnings calendar, with its source and status."


def _en(language: str | None) -> bool:
    return language == "en"


def when_text(earnings: dict[str, Any], language: str = "es") -> str:
    """«hoy» / «mañana» / «el 3 nov 2026» segun la ventana del aviso."""
    en = _en(language)
    window = earnings.get("window")
    if window == "today":
        return "today" if en else "hoy"
    if window == "day":
        return "tomorrow" if en else "mañana"
    if en:
        return f"on {short_date(str(earnings['event_date']), language)}"
    return f"el {fecha_es(str(earnings['event_date']))}"


def title(earnings: dict[str, Any], language: str = "es") -> str:
    if _en(language):
        return f"{earnings['ticker']} reports earnings {when_text(earnings, language)}"
    return f"{earnings['ticker']} presenta resultados {when_text(earnings)}"


def confirmation_text(earnings: dict[str, Any], language: str = "es") -> str:
    """Estado de la fecha tal y como la marca la fuente; sin inventar."""
    en = _en(language)
    confirmed = earnings.get("confirmed")
    if confirmed is True:
        return "Date confirmed by the source" if en else "Fecha confirmada por la fuente"
    if confirmed is False:
        return "Date estimated by the source; it may change" if en else "Fecha estimada por la fuente; puede cambiar"
    return "The source does not say whether the date is confirmed" if en else "La fuente no indica si la fecha esta confirmada"


def detail_rows(earnings: dict[str, Any], language: str = "es") -> list[tuple[str, str]]:
    """Filas etiqueta/valor comunes al texto plano y al HTML."""
    en = _en(language)
    rows: list[tuple[str, str]] = [("Date" if en else "Fecha", short_date(str(earnings["event_date"]), language))]
    session = (SESSION_LABELS_EN if en else SESSION_LABELS).get(str(earnings.get("session") or ""))
    if session:
        if en:
            rows.append(("Session", f"{session} (session published by the source; no exact time)"))
        else:
            rows.append(("Franja", f"{session} (franja publicada por la fuente; sin hora exacta)"))
    rows.append(("Date status" if en else "Estado de la fecha", confirmation_text(earnings, language)))
    if earnings.get("fiscal_label"):
        rows.append(("Reported quarter" if en else "Trimestre comunicado", str(earnings["fiscal_label"])))
    origin = (ORIGIN_LABELS_EN if en else ORIGIN_LABELS).get(str(earnings.get("origin") or ""))
    if origin:
        rows.append(("Tracked from", f"Your {origin}") if en else ("Origen del seguimiento", f"Tu {origin}"))
    if earnings.get("source"):
        rows.append(("Source" if en else "Fuente", str(earnings["source"])))
    return rows


def message_text(earnings: dict[str, Any], language: str = "es") -> str:
    en = _en(language)
    lines = [title(earnings, language)]
    if earnings.get("company_name"):
        lines.append(str(earnings["company_name"]))
    lines.append("")
    lines += [f"{label}: {value}" for label, value in detail_rows(earnings, language)]
    if earnings.get("source_url"):
        lines += ["", f"{'Source link' if en else 'Enlace de la fuente'}: {earnings['source_url']}"]
    lines += ["", DISCLAIMER_EN if en else DISCLAIMER]
    return "\n".join(lines)


def email_content(earnings: dict[str, Any], language: str = "es") -> EmailContent:
    en = _en(language)
    headline = title(earnings, language)
    company = earnings.get("company_name")
    rows_html = "".join(
        "<tr>"
        f"<td style=\"padding:6px 12px 6px 0;color:#555;font-size:13px\">{escape(label)}</td>"
        f"<td style=\"padding:6px 0;font-size:13px;font-weight:600\">{escape(value)}</td>"
        "</tr>"
        for label, value in detail_rows(earnings, language)
    )
    source_url = str(earnings.get("source_url") or "")
    link_html = (
        f"<p style=\"font-size:13px;margin:14px 0 0\">{'Source' if en else 'Fuente'}: "
        f"<a href=\"{escape(source_url, quote=True)}\" style=\"color:#1a56db\">{escape(source_url)}</a></p>"
        if source_url
        else ""
    )
    html = (
        f"<!doctype html><html lang=\"{'en' if en else 'es'}\"><body style=\"margin:0;background:#0b0b0f\">"
        "<div style=\"max-width:560px;margin:0 auto;padding:24px;font-family:Arial,Helvetica,sans-serif;"
        "background:#ffffff;color:#111\">"
        f"<h1 style=\"font-size:22px;margin:0 0 4px\">{escape(headline)}</h1>"
        + (f"<p style=\"margin:0 0 16px;color:#555\">{escape(str(company))}</p>" if company else "")
        + f"<table style=\"margin-top:16px;border-collapse:collapse\">{rows_html}</table>"
        + link_html
        + f"<p style=\"font-size:11px;color:#777;margin:20px 0 0\">{escape(DISCLAIMER_EN if en else DISCLAIMER)} "
        f"{escape(FOOTER_EN if en else FOOTER)}</p>"
        "</div></body></html>"
    )
    subject = headline + (f" · {company}" if company else "")
    return EmailContent(subject=subject[:250], text=message_text(earnings, language), html=html)
