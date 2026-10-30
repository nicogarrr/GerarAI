"""Textos en espanol de los avisos de proximos resultados (titulo, mensaje, correo).

Modulo puro: recibe el diccionario ``earnings`` que ``earnings_reminders``
guarda en ``ResearchAlert.metadata_["earnings"]`` y devuelve texto. Misma
filosofia que ``dca_alert_copy``: solo se muestra lo que existe (una franja o
trimestre ausentes no se pintan) y la fecha nunca se adorna con una hora que
la fuente no publico.
"""

from __future__ import annotations

from html import escape
from typing import Any

from app.services.display_es import fecha_es
from app.services.email_delivery import EmailContent

DISCLAIMER = "Aviso de calendario de resultados; no es asesoramiento financiero."

WINDOWS = ("today", "day", "week")
SESSION_LABELS = {"pre_market": "antes de la apertura", "after_market": "tras el cierre"}
ORIGIN_LABELS = {"cartera": "cartera", "watchlist": "watchlist"}


def when_text(earnings: dict[str, Any]) -> str:
    """«hoy» / «mañana» / «el 3 nov 2026» segun la ventana del aviso."""
    window = earnings.get("window")
    if window == "today":
        return "hoy"
    if window == "day":
        return "mañana"
    return f"el {fecha_es(str(earnings['event_date']))}"


def title(earnings: dict[str, Any]) -> str:
    return f"{earnings['ticker']} presenta resultados {when_text(earnings)}"


def confirmation_text(earnings: dict[str, Any]) -> str:
    """Estado de la fecha tal y como la marca la fuente; sin inventar."""
    confirmed = earnings.get("confirmed")
    if confirmed is True:
        return "Fecha confirmada por la fuente"
    if confirmed is False:
        return "Fecha estimada por la fuente; puede cambiar"
    return "La fuente no indica si la fecha esta confirmada"


def detail_rows(earnings: dict[str, Any]) -> list[tuple[str, str]]:
    """Filas etiqueta/valor comunes al texto plano y al HTML."""
    rows: list[tuple[str, str]] = [("Fecha", fecha_es(str(earnings["event_date"])))]
    session = SESSION_LABELS.get(str(earnings.get("session") or ""))
    if session:
        rows.append(("Franja", f"{session} (franja publicada por la fuente; sin hora exacta)"))
    rows.append(("Estado de la fecha", confirmation_text(earnings)))
    if earnings.get("fiscal_label"):
        rows.append(("Trimestre comunicado", str(earnings["fiscal_label"])))
    origin = ORIGIN_LABELS.get(str(earnings.get("origin") or ""))
    if origin:
        rows.append(("Origen del seguimiento", f"Tu {origin}"))
    if earnings.get("source"):
        rows.append(("Fuente", str(earnings["source"])))
    return rows


def message_text(earnings: dict[str, Any]) -> str:
    lines = [title(earnings)]
    if earnings.get("company_name"):
        lines.append(str(earnings["company_name"]))
    lines.append("")
    lines += [f"{label}: {value}" for label, value in detail_rows(earnings)]
    if earnings.get("source_url"):
        lines += ["", f"Enlace de la fuente: {earnings['source_url']}"]
    lines += ["", DISCLAIMER]
    return "\n".join(lines)


def email_content(earnings: dict[str, Any]) -> EmailContent:
    headline = title(earnings)
    company = earnings.get("company_name")
    rows_html = "".join(
        "<tr>"
        f"<td style=\"padding:6px 12px 6px 0;color:#555;font-size:13px\">{escape(label)}</td>"
        f"<td style=\"padding:6px 0;font-size:13px;font-weight:600\">{escape(value)}</td>"
        "</tr>"
        for label, value in detail_rows(earnings)
    )
    source_url = str(earnings.get("source_url") or "")
    link_html = (
        f"<p style=\"font-size:13px;margin:14px 0 0\">Fuente: "
        f"<a href=\"{escape(source_url, quote=True)}\" style=\"color:#1a56db\">{escape(source_url)}</a></p>"
        if source_url
        else ""
    )
    html = (
        "<!doctype html><html lang=\"es\"><body style=\"margin:0;background:#0b0b0f\">"
        "<div style=\"max-width:560px;margin:0 auto;padding:24px;font-family:Arial,Helvetica,sans-serif;"
        "background:#ffffff;color:#111\">"
        f"<h1 style=\"font-size:22px;margin:0 0 4px\">{escape(headline)}</h1>"
        + (f"<p style=\"margin:0 0 16px;color:#555\">{escape(str(company))}</p>" if company else "")
        + f"<table style=\"margin-top:16px;border-collapse:collapse\">{rows_html}</table>"
        + link_html
        + f"<p style=\"font-size:11px;color:#777;margin:20px 0 0\">{escape(DISCLAIMER)} "
        "La fecha procede del calendario de resultados de GerarAI, con su fuente y estado.</p>"
        "</div></body></html>"
    )
    subject = headline + (f" · {company}" if company else "")
    return EmailContent(subject=subject[:250], text=message_text(earnings), html=html)
