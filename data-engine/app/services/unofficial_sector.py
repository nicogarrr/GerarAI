"""Sector de reserva NO OFICIAL para emisores sin clasificación oficial (Nico, 11-nov-2026: «Si»).

Emisores europeos/extranjeros sin sector, industria ni SIC de la SEC (Airbus, Intertek, SGS…) quedaban fuera de
Piotroski/Altman con «Sector sin clasificar». Aquí se busca, SOLO cuando no hay ninguna clasificación oficial, una
clasificación de fuente gratuita y pública, en este orden:

1. Wikidata: la propiedad «industria» (P452) del elemento con ese ISIN (P946), por su SPARQL público.
2. Yahoo Finance: sector del perfil (``assetProfile.sectorKey``) del símbolo, con prueba de identidad por nombre.

Reglas (deterministas: misma respuesta de la fuente → mismo sector):
- Las industrias se pasan a la taxonomía interna (GICS de 11 sectores) con una tabla general de palabras clave
  (nunca por ticker). Una industria que encaja en dos sectores, o industrias que dan sectores distintos, son una
  respuesta AMBIGUA: no se elige ninguno.
- Wikidata decide si da un único sector. Si falta o no se puede mapear, decide Yahoo. Si Wikidata es ambigua, Yahoo
  solo vale cuando su sector es uno de los candidatos de Wikidata; si no, «Sector sin clasificar» con el motivo.
- Se guarda con su fuente, URL y fecha de consulta en ``connector_states`` (conector ``sector-no-oficial``), y se
  muestra siempre como «no oficial». La clasificación oficial manda siempre: esto nunca escribe Company.sector.
- Educado con las fuentes: caché (180 días con respuesta, 30 sin ella), una consulta por fuente, sin reintentos, y un
  429 detiene la fuente durante el resto de la hora (o lo que diga Retry-After).
"""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, ConnectorState

logger = logging.getLogger(__name__)

CONNECTOR = "sector-no-oficial"
RULES_VERSION = "sector-no-oficial-v1"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
YAHOO_PROFILE = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
USER_AGENT = "GerarAI/1.0 (https://github.com/nicogarrr/gerarai; tab@tab.bot) sector-no-oficial"
TTL_FOUND = timedelta(days=180)
TTL_MISSING = timedelta(days=30)
_PLACEHOLDERS = {"", "unknown", "other", "otros", "n/a", "none", "-"}
_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

# Yahoo publica 11 claves de sector estables (sectorKey); equivalencia con los 11 sectores GICS de la app.
YAHOO_SECTOR_KEYS: dict[str, str] = {
    "basic-materials": "Materials",
    "communication-services": "Communication Services",
    "consumer-cyclical": "Consumer Discretionary",
    "consumer-defensive": "Consumer Staples",
    "energy": "Energy",
    "financial-services": "Financials",
    "healthcare": "Health Care",
    "industrials": "Industrials",
    "real-estate": "Real Estate",
    "technology": "Information Technology",
    "utilities": "Utilities",
}

# Industrias de Wikidata (etiqueta en inglés) → sector GICS. Palabras con límite de palabra; una etiqueta que
# encaja en dos sectores («coal mining»: energía y materiales) es ambigua y no se resuelve.
_WIKIDATA_RULES: tuple[tuple[str, str], ...] = (
    (r"aerospace|aviation|aircraft|spaceflight|space industry|arms industry|defen[cs]e industry|shipbuilding|"
     r"construction|civil engineering|engineering|machine industry|machinery|logistics|freight|rail transport|"
     r"railway|airline|shipping|transport|testing|inspection|certification|business services|"
     r"professional services|consulting|staffing|waste management|electrical equipment", "Industrials"),
    (r"software|semiconductor|information technology|computer|electronics|cloud computing|it services?",
     "Information Technology"),
    (r"telecommunications?|telecom|mass media|media industry|broadcasting|publishing|video games?|"
     r"entertainment|advertising|social media", "Communication Services"),
    (r"pharmaceutical|biotechnology|health ?care|medical|hospital|diagnostics?|life sciences?", "Health Care"),
    (r"bank(?:ing)?|financ\w*|insurance|investment|asset management|stock exchange", "Financials"),
    (r"real estate", "Real Estate"),
    (r"petroleum|oil|natural gas|coal", "Energy"),
    (r"electric utility|electricity generation|electric power|water supply|public utility|utilities", "Utilities"),
    (r"mining|metals?|steel|chemicals?|chemical industry|paper|packaging|building materials|cement|glass",
     "Materials"),
    (r"automotive|automobile|retail|hotels?|hospitality|restaurants?|clothing|fashion|apparel|luxury|tourism|"
     r"e-commerce|toys?", "Consumer Discretionary"),
    (r"food|beverages?|drinks?|brewing|brewery|tobacco|supermarkets?|grocery|household products|personal care|"
     r"cosmetics", "Consumer Staples"),
)
_COMPILED = tuple((re.compile(rf"\b(?:{pat})\b", re.IGNORECASE), sector) for pat, sector in _WIKIDATA_RULES)

# Fuente detenida tras un 429 (host → epoch hasta el que no se pregunta).
_HALTED: dict[str, float] = {}


def known(label: Any) -> bool:
    return str(label or "").strip().lower() not in _PLACEHOLDERS


def sectors_for_label(label: str) -> list[str]:
    """Sectores GICS en los que encaja una etiqueta de industria (ordenados). Puro."""
    return sorted({sector for rx, sector in _COMPILED if rx.search(label or "")})


def verdict_from_wikidata(industries: Iterable[tuple[str, str]]) -> dict[str, Any]:
    """{status: ok|ambiguous|missing, sector, candidates, industries, reason} de las industrias P452. Puro."""
    rows = sorted({(str(q), str(lbl)) for q, lbl in industries if lbl}, key=lambda r: (r[1].lower(), r[0]))
    labels = [lbl for _q, lbl in rows]
    if not rows:
        return {"status": "missing", "sector": None, "candidates": [], "industries": [],
                "reason": "Wikidata no tiene industria (P452) para este ISIN"}
    candidates = sorted({s for lbl in labels for s in sectors_for_label(lbl)})
    mapped = [lbl for lbl in labels if sectors_for_label(lbl)]
    if not candidates:
        return {"status": "missing", "sector": None, "candidates": [], "industries": labels,
                "reason": "las industrias de Wikidata (" + ", ".join(labels) + ") no encajan en ningún sector"}
    if len(candidates) > 1:
        return {"status": "ambiguous", "sector": None, "candidates": candidates, "industries": labels,
                "reason": "las industrias de Wikidata (" + ", ".join(mapped) + ") apuntan a varios sectores: "
                          + ", ".join(candidates)}
    return {"status": "ok", "sector": candidates[0], "candidates": candidates, "industries": labels,
            "reason": None}


def verdict_from_yahoo(profile: Mapping[str, Any] | None) -> dict[str, Any]:
    """Veredicto del perfil de Yahoo (``sectorKey`` estable; la etiqueta solo se guarda). Puro."""
    if not profile:
        return {"status": "missing", "sector": None, "industry": None,
                "reason": "Yahoo no da perfil para este símbolo"}
    key = str(profile.get("sectorKey") or "").strip().lower()
    sector = YAHOO_SECTOR_KEYS.get(key)
    industry = str(profile.get("industry") or "").strip() or None
    if sector is None:
        return {"status": "missing", "sector": None, "industry": industry,
                "reason": f"Yahoo no da un sector reconocible ({key or 'vacío'})"}
    return {"status": "ok", "sector": sector, "industry": industry, "yahoo_sector": profile.get("sector"),
            "reason": None}


def decide(wikidata: Mapping[str, Any] | None, yahoo: Mapping[str, Any] | None) -> dict[str, Any]:
    """Sector de reserva y de dónde sale, o sin sector con el motivo. Puro y determinista."""
    wd = dict(wikidata or {"status": "missing", "reason": "Wikidata no consultada"})
    yh = dict(yahoo or {"status": "missing", "reason": "Yahoo no consultado"})
    if wd.get("status") == "ok":
        return {"sector": wd["sector"], "source": "Wikidata", "industry": ", ".join(wd.get("industries") or []),
                "source_url": wd.get("source_url"), "reason": None}
    if yh.get("status") == "ok":
        if wd.get("status") == "ambiguous" and yh["sector"] not in (wd.get("candidates") or []):
            return {"sector": None, "source": None, "industry": None, "source_url": None,
                    "reason": f"{wd.get('reason')}; Yahoo da otro ({yh['sector']}): fuentes no oficiales discrepan"}
        return {"sector": yh["sector"], "source": "Yahoo Finance", "industry": yh.get("industry"),
                "source_url": yh.get("source_url"), "reason": None}
    return {"sector": None, "source": None, "industry": None, "source_url": None,
            "reason": "; ".join(str(x) for x in (wd.get("reason"), yh.get("reason")) if x)}


def lacks_official(company: Any, sic_sector: str | None) -> bool:
    """Sin sector, sin industria y sin división SIC: no hay ninguna clasificación oficial."""
    return not known(getattr(company, "sector", None)) and not known(getattr(company, "industry", None)) \
        and not known(sic_sector)


# -- red ---------------------------------------------------------------------------------------------------------

class SourceHalted(RuntimeError):
    """La fuente pidió parar (429): no se le pregunta más en esta ventana."""


def _halted(host: str) -> bool:
    return _HALTED.get(host, 0.0) > time.time()


def _halt(host: str, response: httpx.Response) -> None:
    try:
        wait = float(response.headers.get("Retry-After") or 3600)
    except ValueError:
        wait = 3600.0
    _HALTED[host] = time.time() + max(wait, 60.0)


def _get(client: httpx.Client, host: str, url: str, **kw: Any) -> httpx.Response:
    if _halted(host):
        raise SourceHalted(host)
    response = client.get(url, **kw)
    if response.status_code == 429:
        _halt(host, response)
        raise SourceHalted(host)
    response.raise_for_status()
    return response


def fetch_wikidata(client: httpx.Client, isin: str) -> dict[str, Any]:
    query = ('SELECT ?item ?ind ?indLabel WHERE { ?item wdt:P946 "' + isin + '" . OPTIONAL { ?item wdt:P452 ?ind . } '
             'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }')
    response = _get(client, "wikidata", WIKIDATA_SPARQL, params={"query": query, "format": "json"},
                    headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})
    bindings = (response.json().get("results") or {}).get("bindings") or []
    items = sorted({str((b.get("item") or {}).get("value", "")).rsplit("/", 1)[-1] for b in bindings} - {""})
    if len(items) > 1:  # identidad dudosa: no es una respuesta de sector, pasa a la siguiente fuente
        return {"status": "missing", "sector": None, "candidates": [], "industries": [],
                "reason": f"Wikidata tiene {len(items)} elementos con ese ISIN ({', '.join(items)})"}
    if not items:
        return {"status": "missing", "sector": None, "candidates": [], "industries": [],
                "reason": "Wikidata no tiene ningún elemento con ese ISIN"}
    industries = [(str((b.get("ind") or {}).get("value", "")).rsplit("/", 1)[-1],
                   str((b.get("indLabel") or {}).get("value", ""))) for b in bindings if b.get("ind")]
    out = verdict_from_wikidata(industries)
    out["source_url"] = f"https://www.wikidata.org/wiki/{items[0]}"
    return out


def _yahoo_crumb(client: httpx.Client) -> str:
    """Cookie de fc.yahoo.com + crumb (el mismo flujo que earnings_dates_service), sin reintentos."""
    client.get("https://fc.yahoo.com", headers={"User-Agent": "Mozilla/5.0"})  # 404 esperado: fija la cookie
    crumb = _get(client, "yahoo", "https://query1.finance.yahoo.com/v1/test/getcrumb",
                 headers={"User-Agent": "Mozilla/5.0"}).text.strip()
    if not crumb or " " in crumb or len(crumb) > 40:
        raise RuntimeError("yahoo_crumb_unavailable")
    return crumb


def fetch_yahoo(client: httpx.Client, symbol: str, company_name: str | None) -> dict[str, Any]:
    from app.services.financial_ingestion_service import _name_identity_ok

    if _halted("yahoo"):
        raise SourceHalted("yahoo")
    crumb = _yahoo_crumb(client)
    response = _get(client, "yahoo", YAHOO_PROFILE.format(symbol=symbol),
                    params={"modules": "assetProfile,price", "crumb": crumb}, headers={"User-Agent": "Mozilla/5.0"})
    result = ((response.json().get("quoteSummary") or {}).get("result") or [None])[0] or {}
    price = result.get("price") or {}
    names = [price.get("longName"), price.get("shortName")]
    if not any(_name_identity_ok(company_name, n) for n in names if n):
        return {"status": "missing", "sector": None, "industry": None,
                "reason": f"el perfil de Yahoo de {symbol} es de otra empresa ({names[0] or names[1] or 'sin nombre'})"}
    out = verdict_from_yahoo(result.get("assetProfile"))
    out["source_url"] = f"https://finance.yahoo.com/quote/{symbol}/profile"
    return out


# -- caché ----------------------------------------------------------------------------------------------------

def _row(db: Session, company: Company) -> ConnectorState | None:
    return db.scalar(select(ConnectorState).where(ConnectorState.connector == CONNECTOR,
                                                  ConnectorState.company_id == company.id))


def _fresh(state: ConnectorState, now: datetime) -> bool:
    meta = state.metadata_ or {}
    if meta.get("rules_version") != RULES_VERSION or state.last_success_at is None:
        return False
    last = state.last_success_at if state.last_success_at.tzinfo else state.last_success_at.replace(tzinfo=UTC)
    return now - last < (TTL_FOUND if meta.get("sector") else TTL_MISSING)


def refresh(db: Session, company: Company, *, client: httpx.Client | None = None,
            sic_sector: str | None = None, now: datetime | None = None) -> dict[str, Any] | None:
    """Consulta (o reutiliza de la caché) el sector no oficial. Nunca lanza; None si no aplica.

    Solo para fichas sin ninguna clasificación oficial y con ISIN (la identidad que ancla la consulta)."""
    now = now or datetime.now(UTC)
    isin = str(getattr(company, "isin", None) or "").strip().upper()
    if company.id is None or not lacks_official(company, sic_sector) or not _ISIN.match(isin):
        return None
    state = _row(db, company)
    if state is not None and _fresh(state, now):
        return dict(state.metadata_ or {})
    own = client is None
    http = client or httpx.Client(timeout=8, follow_redirects=True)
    if state is None:
        state = ConnectorState(connector=CONNECTOR, company_id=company.id, consecutive_errors=0, metadata_={})
        db.add(state)
    state.last_started_at = now
    errors: list[str] = []
    wd: dict[str, Any] | None = None
    yh: dict[str, Any] | None = None
    try:
        try:
            wd = fetch_wikidata(http, isin)
        except Exception as exc:  # noqa: BLE001 - fuente caída o 429: se anota, no se reintenta
            errors.append(f"wikidata: {type(exc).__name__}")
        if wd is None or wd.get("status") != "ok":
            try:
                yh = fetch_yahoo(http, company.ticker, company.name)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"yahoo: {type(exc).__name__}")
    finally:
        if own:
            http.close()
    if errors and not ((wd or {}).get("status") == "ok" or (yh or {}).get("status") == "ok"):
        # Sin respuesta completa no se fija un «sin sector»: se reintenta en el siguiente enriquecimiento.
        state.consecutive_errors = int(state.consecutive_errors or 0) + 1
        state.last_error = "; ".join(errors)
        return dict(state.metadata_ or {}) or None
    verdict = decide(wd, yh)
    verdict.update({"rules_version": RULES_VERSION, "checked_at": now.date().isoformat(), "isin": isin,
                    "official": False})
    state.metadata_ = verdict
    state.feed_url = verdict.get("source_url")
    state.last_success_at = now
    state.consecutive_errors = 0
    state.last_error = None
    return dict(verdict)


def stored(db: Session, company_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    """Veredictos guardados por company_id (sin red)."""
    ids = [i for i in company_ids if i is not None]
    if not ids:
        return {}
    rows = db.scalars(select(ConnectorState).where(ConnectorState.connector == CONNECTOR,
                                                   ConnectorState.company_id.in_(ids))).all()
    return {r.company_id: dict(r.metadata_ or {}) for r in rows
            if r.company_id is not None and (r.metadata_ or {}).get("rules_version") == RULES_VERSION}


def health_basis(verdict: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Lo que Piotroski/Altman muestran del sector no oficial (fuente y fecha a la vista)."""
    if not verdict:
        return None
    day = str(verdict.get("checked_at") or "")
    try:
        shown = datetime.fromisoformat(day).strftime("%d/%m/%Y")
    except ValueError:
        shown = day or "fecha desconocida"
    if not verdict.get("sector"):
        return {"sector": None, "official": False, "reason": verdict.get("reason"), "checked_at": day or None}
    return {"sector": verdict["sector"], "official": False, "source": verdict.get("source"),
            "source_url": verdict.get("source_url"), "industry": verdict.get("industry") or None,
            "checked_at": day or None,
            "label": f"Sector no oficial: {verdict['sector']} (según {verdict.get('source')}, consultado el {shown}); "
                     "el emisor no tiene clasificación oficial"}
