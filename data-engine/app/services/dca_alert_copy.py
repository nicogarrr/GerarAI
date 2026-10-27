"""Textos en espanol de las alertas DCA (titulo, mensaje, correo HTML).

Modulo puro: recibe el diccionario ``dca`` que el servicio guarda en
``ResearchAlert.metadata_["dca"]`` y devuelve texto. Imita la estructura del
correo de DCA Optimizer (titular, badge del nivel en su color, zona, estado
del mes, fecha de senal y cierre asentado) con las metricas de la formula
propia. Solo muestra lo que existe: una metrica ausente no se pinta.
"""

from __future__ import annotations

from html import escape
from typing import Any

from app.services.display_es import fecha_es
from app.services.email_delivery import EmailContent

DISCLAIMER = "Apoyo a la decisión, no asesoramiento financiero."

STATUS_LABELS = {"forming": "mes en formación", "confirmed": "mes confirmado"}


def currency_label(currency: str | None) -> str | None:
    """Codigo de divisa visible. Las lineas de Londres cotizan en peniques."""
    if not currency:
        return None
    code = currency.strip()
    if code in {"GBX", "GBp", "GBx"}:
        return "GBX (peniques)"
    return code.upper()


def number_es(value: float, decimals: int = 2) -> str:
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "@").replace(".", ",").replace("@", ".")


def price_es(value: float | None, currency: str | None) -> str | None:
    if value is None:
        return None
    label = currency_label(currency)
    decimals = 2 if abs(value) >= 1 else 4
    number = number_es(float(value), decimals)
    return f"{number} {label}" if label else number


def percent_es(value: float | None, decimals: int = 1) -> str | None:
    if value is None:
        return None
    return f"{number_es(float(value) * 100, decimals)} %"


def is_drop(dca: dict[str, Any]) -> bool:
    """Aviso de bajada de nivel (informativo, no una senal nueva)."""
    return dca.get("direction") == "down"


def title(dca: dict[str, Any]) -> str:
    if is_drop(dca):
        previous = dca.get("previous_label")
        suffix = f" (desde {previous})" if previous else ""
        return f"{dca['symbol']} baja a {dca['label']}{suffix}"
    return f"{dca['symbol']} entró en {dca['label']}"


def drop_note(dca: dict[str, Any]) -> str | None:
    if not is_drop(dca):
        return None
    previous = dca.get("previous_label")
    origin = f" desde {previous}" if previous else ""
    return f"Aviso informativo: el nivel baja{origin} a {dca['label']}."


def signal_metric(dca: dict[str, Any]) -> tuple[str, str] | None:
    """(etiqueta, valor) de la metrica que decide el nivel de compra."""
    metrics = dca.get("metrics") or {}
    if metrics.get("signal") == "sma_gap" and metrics.get("sma_gap") is not None:
        months = dca.get("sma_months")
        label = f"Distancia bajo media {months}m" if months else "Distancia bajo media larga"
        return label, percent_es(metrics["sma_gap"]) or ""
    if metrics.get("drawdown") is not None:
        months = dca.get("high_lookback_months")
        label = f"Caída desde máximo {months}m" if months else "Caída desde máximo"
        return label, percent_es(metrics["drawdown"]) or ""
    return None


def detail_rows(dca: dict[str, Any]) -> list[tuple[str, str]]:
    """Filas etiqueta/valor comunes al texto plano y al HTML."""
    rows: list[tuple[str, str]] = []
    rows.append(("Zona", str(dca.get("zone") or "")))
    rows.append(("Estado", STATUS_LABELS.get(str(dca.get("status")), str(dca.get("status") or ""))))
    if dca.get("signal_date"):
        rows.append(("Fecha de señal", fecha_es(dca["signal_date"])))
    close = price_es(dca.get("close"), dca.get("currency"))
    if close:
        rows.append(("Cierre asentado", close))
    metric = signal_metric(dca)
    if metric:
        rows.append(metric)
    rsi = (dca.get("metrics") or {}).get("rsi")
    if rsi is not None:
        rows.append(("RSI mensual", number_es(float(rsi), 1)))
    prices = dca.get("level_prices") or {}
    for key in ("2x", "3x", "4x"):
        value = price_es(prices.get(key), dca.get("currency"))
        if value:
            rows.append((f"Cierre que activaría {key.upper()}", value))
    sources = dca.get("sources") or []
    if sources:
        names = {"watchlist": "watchlist", "portfolio": "cartera"}
        rows.append(("Origen", " + ".join(names.get(str(s), str(s)) for s in sources)))
    return rows


def message_text(dca: dict[str, Any]) -> str:
    lines = [title(dca)]
    if dca.get("company_name"):
        lines.append(str(dca["company_name"]))
    lines.append("")
    note = drop_note(dca)
    if note:
        lines += [note, ""]
    lines += [f"{label}: {value}" for label, value in detail_rows(dca)]
    if dca.get("status") == "forming":
        lines += ["", "El mes aún no ha cerrado: el veredicto puede cambiar hasta el último cierre del mes."]
    lines += ["", DISCLAIMER]
    return "\n".join(lines)


def email_content(dca: dict[str, Any]) -> EmailContent:
    headline = title(dca)
    color = str(dca.get("color") or "#FFFFFF")
    fg = str(dca.get("fg") or "#000000")
    company = dca.get("company_name")
    rows_html = "".join(
        "<tr>"
        f"<td style=\"padding:6px 12px 6px 0;color:#555;font-size:13px\">{escape(label)}</td>"
        f"<td style=\"padding:6px 0;font-size:13px;font-weight:600\">{escape(value)}</td>"
        "</tr>"
        for label, value in detail_rows(dca)
    )
    forming_note = (
        "<p style=\"font-size:12px;color:#555;margin:12px 0 0\">El mes aún no ha cerrado: "
        "el veredicto puede cambiar hasta el último cierre del mes.</p>"
        if dca.get("status") == "forming"
        else ""
    )
    html = (
        "<!doctype html><html lang=\"es\"><body style=\"margin:0;background:#0b0b0f\">"
        "<div style=\"max-width:560px;margin:0 auto;padding:24px;font-family:Arial,Helvetica,sans-serif;"
        "background:#ffffff;color:#111\">"
        f"<h1 style=\"font-size:22px;margin:0 0 4px\">{escape(headline)}</h1>"
        + (f"<p style=\"margin:0 0 16px;color:#555\">{escape(str(company))}</p>" if company else "")
        + f"<span style=\"display:inline-block;padding:6px 14px;border-radius:999px;background:{escape(color)};"
        f"color:{escape(fg)};font-weight:700;border:1px solid #d0d0d0\">{escape(str(dca['label']))}</span>"
        + (f"<p style=\"margin:12px 0 0;color:#555\">{escape(drop_note(dca) or '')}</p>" if is_drop(dca) else "")
        + f"<table style=\"margin-top:16px;border-collapse:collapse\">{rows_html}</table>"
        + forming_note
        + f"<p style=\"font-size:11px;color:#777;margin:20px 0 0\">{escape(DISCLAIMER)} "
        "Señal generada por GerarAI con la fórmula DCA propia a partir de cierres diarios asentados.</p>"
        "</div></body></html>"
    )
    subject = f"{headline}" + (f" · {company}" if company else "")
    return EmailContent(subject=subject[:250], text=message_text(dca), html=html)
