"""Calendario macro oficial: reuniones FOMC (Reserva Federal) y publicaciones BLS.

Dos fuentes publicas, gratuitas y sin clave:

* FOMC: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
* BLS: https://www.bls.gov/schedule/news_release/bls.ics (iCalendar oficial).
  BLS bloquea clientes sin contacto declarado: se envia ``sec_user_agent``,
  que ya lleva un email de contacto.

Los parsers son funciones puras. Nunca se inventa una fecha: si una fuente no
responde o su formato cambia, devuelven lista vacia y el servicio lo marca como
``unavailable`` en vez de rellenar con un calendario recordado.
"""

from __future__ import annotations

import re
import time
from datetime import date
from html import unescape
from typing import Any

import httpx

from app.services.data_source_health import get_data_source_registry

# Claves en el registry de salud de fuentes. Las URLs son fijas (no llevan
# ticker): un 404 aqui SI es fuente caida o movida, a diferencia de Yahoo/SEC.
FOMC_REGISTRY_KEY = "fomc_calendar"
BLS_REGISTRY_KEY = "bls_calendar"

FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BLS_SCHEDULE_URL = "https://www.bls.gov/schedule/news_release/"

_MONTHS = {
    name: index
    for index, name in enumerate(
        [
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ],
        start=1,
    )
}
_YEAR_PANEL = re.compile(r'<h4><a id="\d+">(\d{4}) FOMC Meetings</a>')
_MEETING = re.compile(
    r"fomc-meeting__month[^>]*>\s*<strong>([^<]*)</strong>.*?"
    r"fomc-meeting__date[^>]*>([^<]*)<",
    re.S,
)
_DAYS = re.compile(r"^\s*(\d{1,2})(?:\s*-\s*(\d{1,2}))?\s*(\*)?\s*$")


def _month_number(label: str) -> int | None:
    return _MONTHS.get(label.strip()[:3].lower())


def parse_fomc_html(html: str) -> list[dict[str, Any]]:
    """Reuniones FOMC programadas. Devuelve ``date`` = ultimo dia (decision).

    Ignora votos por notacion (sin rango de dias) y filas que no se pueden
    leer con certeza. ``projections`` marca las reuniones con asterisco
    (Resumen de Proyecciones Economicas).
    """
    panels = list(_YEAR_PANEL.finditer(html))
    events: list[dict[str, Any]] = []
    for index, panel in enumerate(panels):
        year = int(panel.group(1))
        end = panels[index + 1].start() if index + 1 < len(panels) else len(html)
        for meeting in _MEETING.finditer(html, panel.end(), end):
            months = [m for m in unescape(meeting.group(1)).split("/") if m.strip()]
            parsed = _DAYS.match(unescape(meeting.group(2)))
            if not months or parsed is None or parsed.group(2) is None:
                continue
            start_day, end_day = int(parsed.group(1)), int(parsed.group(2))
            start_month = _month_number(months[0])
            end_month = _month_number(months[-1])
            if start_month is None or end_month is None:
                continue
            try:
                start = date(year, start_month, start_day)
                decision = date(year, end_month, end_day)
            except ValueError:
                continue
            if decision < start:
                continue
            events.append(
                {
                    "kind": "fomc",
                    "start_date": start.isoformat(),
                    "date": decision.isoformat(),
                    "projections": parsed.group(3) == "*",
                }
            )
    return events


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def parse_bls_ics(text: str) -> list[dict[str, Any]]:
    """Eventos del iCalendar de BLS: titulo, fecha y hora local (ET)."""
    events: list[dict[str, Any]] = []
    current: dict[str, str] | None = None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT" and current is not None:
            summary = current.get("SUMMARY", "").strip()
            stamp = re.search(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2}))?", current.get("DTSTART", ""))
            if summary and stamp:
                try:
                    day = date(int(stamp.group(1)), int(stamp.group(2)), int(stamp.group(3)))
                except ValueError:
                    day = None
                if day is not None:
                    time_et = f"{stamp.group(4)}:{stamp.group(5)}" if stamp.group(4) else None
                    events.append({"title": summary, "date": day.isoformat(), "time_et": time_et})
            current = None
        elif current is not None and ":" in line:
            key, _, value = line.partition(":")
            current.setdefault(key.split(";")[0], value)
    return events


async def _get_text(url: str, user_agent: str, client: httpx.AsyncClient | None) -> str:
    headers = {"User-Agent": user_agent, "Accept": "*/*"}
    if client is not None:
        response = await client.get(url, headers=headers)
    else:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as owned:
            response = await owned.get(url, headers=headers)
    response.raise_for_status()
    return response.text


async def fetch_fomc(user_agent: str, client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    registry = get_data_source_registry()
    started = time.perf_counter()
    try:
        text = await _get_text(FOMC_URL, user_agent, client)
    except httpx.HTTPStatusError as exc:
        registry.record_failure(FOMC_REGISTRY_KEY, f"HTTP {exc.response.status_code}")
        raise
    except httpx.TransportError as exc:
        registry.record_failure(FOMC_REGISTRY_KEY, f"error de red: {type(exc).__name__}")
        raise
    registry.record_success(FOMC_REGISTRY_KEY, (time.perf_counter() - started) * 1000)
    return parse_fomc_html(text)


async def fetch_bls(user_agent: str, client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    registry = get_data_source_registry()
    started = time.perf_counter()
    try:
        text = await _get_text(BLS_ICS_URL, user_agent, client)
    except httpx.HTTPStatusError as exc:
        registry.record_failure(BLS_REGISTRY_KEY, f"HTTP {exc.response.status_code}")
        raise
    except httpx.TransportError as exc:
        registry.record_failure(BLS_REGISTRY_KEY, f"error de red: {type(exc).__name__}")
        raise
    if "BEGIN:VCALENDAR" not in text:
        # BLS responde 200 con una pagina "Access Denied" a clientes no conformes.
        registry.record_failure(BLS_REGISTRY_KEY, "200 sin iCalendar (Access Denied o cambio de formato)")
        raise ValueError("BLS no devolvio un iCalendar")
    registry.record_success(BLS_REGISTRY_KEY, (time.perf_counter() - started) * 1000)
    return parse_bls_ics(text)
