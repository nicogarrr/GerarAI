"""Calendario de proximas llamadas/resultados con FUENTE y grado de fiabilidad explicitos.

Dos clases, nunca mezcladas:
- "anuncio_emisor": fecha leida en un comunicado/pagina del propio emisor (o su distribuidor de
  comunicados) con URL y fecha de lectura.
- "app_calendario_observado": fecha mostrada por el calendario de la app de Nico el 2026-10-22; NO es
  confirmacion oficial de la llamada ni de que haya transcripcion.
Ausencia en este registro = "sin fecha conocida", no "sin llamada".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

ANUNCIO_EMISOR = "anuncio_emisor"
APP_OBSERVADO = "app_calendario_observado"
_READ_ON = "2026-10-22"


@dataclass(frozen=True)
class UpcomingCall:
    ticker: str
    date: str  # AAAA-MM-DD (fecha de la llamada para anuncio_emisor; "proximos resultados" para app)
    kind: str  # anuncio_emisor | app_calendario_observado
    event: str
    source_url: str | None
    read_on: str = _READ_ON
    detail: str = ""

    def __post_init__(self) -> None:
        if self.kind not in (ANUNCIO_EMISOR, APP_OBSERVADO):
            raise ValueError("clase de fecha desconocida")
        if self.kind == ANUNCIO_EMISOR and not (self.source_url or "").startswith("https://"):
            raise ValueError("un anuncio del emisor exige URL https")
        date.fromisoformat(self.date)


_APP = "https://gerarai.vercel.app/watchlist"

CALLS: tuple[UpcomingCall, ...] = (
    UpcomingCall(
        "CPT", "2026-11-06", ANUNCIO_EMISOR, "Q3 2026 conference call",
        "https://www.nasdaq.com/press-release/camden-property-trust-announces-third-quarter-2026-earnings-release-and-conference",
        detail="Comunicado de Camden (Business Wire, via Nasdaq, 2026-10-07): resultados tras cierre "
               "jueves 2026-11-05; llamada viernes 2026-11-06 10:00 CT.",
    ),
    UpcomingCall(
        "ABCL", "2026-11-09", ANUNCIO_EMISOR, "Q3 2026 earnings call",
        "https://investors.abcellera.com/news/news-releases/2026/AbCellera-to-Report-Third-Quarter-2026-Financial-Results-on-November-9-2026/default.aspx",
        detail="Comunicado del IR: llamada lunes 2026-11-09 15:00 PT / 17:00 ET.",
    ),
    UpcomingCall(
        "NAUT", "2026-10-27", ANUNCIO_EMISOR, "Q3 2026 earnings conference call",
        "https://investors.nautilus.bio/events/event-details/nautilus-q3-2026-earnings-conference-call/",
        detail="Pagina de evento del IR: Oct 27, 2026 8:30 AM EDT.",
    ),
    UpcomingCall("CGEO.L", "2026-10-28", APP_OBSERVADO, "Proximos resultados (app)", _APP),
    UpcomingCall("BN", "2026-11-12", APP_OBSERVADO, "Proximos resultados (app)", _APP),
    UpcomingCall("KKR", "2026-11-09", APP_OBSERVADO, "Proximos resultados (app)", _APP),
)


def next_calls(ticker: str, today: date) -> list[dict]:
    """Proximas fechas conocidas (>= today) para un ticker, con clase y fuente."""
    out = []
    for c in CALLS:
        if c.ticker == ticker and date.fromisoformat(c.date) >= today:
            out.append({"date": c.date, "kind": c.kind, "event": c.event,
                        "source_url": c.source_url, "read_on": c.read_on, "detail": c.detail,
                        "official_confirmation": c.kind == ANUNCIO_EMISOR})
    return sorted(out, key=lambda x: x["date"])
