"""Snapshot ESEF «en vivo» para cualquier emisor UE/EEE/UK del indice filings.xbrl.org.

Hasta noviembre de 2026 ``refresh_from_esef`` solo leia el snapshot LOCAL
construido por ``scripts/build_esef_snapshots.py`` (emisores IBEX revisados y
ASML). Caso real (prod, 2026-11-03): Basic-Fit N.V. (BFIT.AS, Euronext
Amsterdam) entra en la watchlist, tiene 255 precios y 0 hechos financieros, y
su tesis se queda en «datos insuficientes» con «Sin snapshot ESEF local». Sus
cinco informes anuales ESEF (2021-2025) estan en filings.xbrl.org desde hace
meses.

Este modulo construye el MISMO snapshot (misma forma que el del script:
lei/entity_name/period_end/periods/fxo_id/sha256/fetched_at/facts) para un
emisor concreto, sin tabla revisada:

1. Identidad. El LEI sale, por este orden, de
   a) el ISIN de la Company (o el del listado revisado de
      ``listing_identity``) via la API publica de GLEIF (``filter[isin]``):
      prueba fuerte, el registro ISIN->LEI lo mantiene GLEIF;
   b) el nombre legal via GLEIF ``filter[fulltext]``, restringido a la
      jurisdiccion del mercado del ticker y con la prueba de nombre de
      ``_name_identity_ok``. Mas de un candidato con filings = ambiguo: no se
      elige (N/D honesto, nunca hechos de otra entidad).
2. Filings del LEI en filings.xbrl.org (``/api/entities/{lei}/filings``):
   hasta 5 ejercicios con render xBRL-JSON, normalizados y fusionados con
   las mismas funciones que el script (``normalize_xbrl_json``,
   ``filings_per_lei``, ``merge_facts``).

Cobertura medida 2026-11-03: el indice tiene ESEF de NL, FR, IT, BE, ES,
paises nordicos y 2.970 filings de emisores del Reino Unido (UKSEF, misma
forma iXBRL->xBRL-JSON, mismo camino). Alemania no esta (publica en el
Bundesanzeiger): esas empresas caen a la reserva Yahoo etiquetada.

Nunca escribe en la BD y nunca lanza por red: devuelve ``None`` con el motivo
en ``last_reason`` del resultado de ``resolve_issuer``/``fetch_live_snapshot``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.connectors.esef import (
    EsefClient,
    EsefError,
    filings_per_lei,
    gleif_http_client,
    gleif_lei_records,
    merge_facts,
    normalize_xbrl_json,
)

logger = logging.getLogger(__name__)

LIVE_SOURCE = "filings.xbrl.org (indice ESEF/UKSEF de XBRL International), consulta en vivo por LEI"

# Sufijo de ticker (Yahoo) -> jurisdiccion del emisor mas probable. Solo
# acota la busqueda por nombre; con ISIN no se usa.
SUFFIX_JURISDICTION: dict[str, str] = {
    "AS": "NL", "PA": "FR", "BR": "BE", "LS": "PT", "MC": "ES", "MI": "IT",
    "DE": "DE", "F": "DE", "VI": "AT", "HE": "FI", "ST": "SE", "CO": "DK",
    "OL": "NO", "IR": "IE", "L": "GB", "IL": "GB", "WA": "PL", "AT": "GR",
    "PR": "CZ", "BD": "HU", "LU": "LU",
}


def live_lookup_enabled() -> bool:
    """Interruptor de las fuentes de red para emisores sin SEC (la suite lo apaga)."""
    from app.core.config import get_settings

    return bool(getattr(get_settings(), "non_sec_fundamentals_fallback_enabled", True))


@dataclass(frozen=True)
class IssuerIdentity:
    lei: str
    legal_name: str
    method: str  # "isin_gleif" | "name_gleif"
    isin: str | None = None


def _ticker_suffix(ticker: str) -> str:
    t = (ticker or "").upper()
    return t.rsplit(".", 1)[-1] if "." in t else ""


def _company_isin(company: Any) -> str | None:
    isin = (getattr(company, "isin", None) or "").strip().upper()
    if isin:
        return isin
    from app.services.listing_identity import reviewed_listing_for_ticker

    listing = reviewed_listing_for_ticker(getattr(company, "ticker", None))
    return listing.isin if listing else None


def _placeholder_name(company: Any) -> bool:
    name = (getattr(company, "name", None) or "").strip().upper()
    return name in {"", (getattr(company, "ticker", None) or "").strip().upper(), "UNKNOWN"}


def _record(row: dict[str, Any]) -> tuple[str, str, str, str] | None:
    try:
        attrs = row["attributes"]
        entity = attrs["entity"]
        return (
            str(attrs["lei"]),
            str(entity["legalName"]["name"]),
            str(entity.get("jurisdiction") or ""),
            str((attrs.get("registration") or {}).get("status") or ""),
        )
    except (KeyError, TypeError):
        return None


async def resolve_issuer(
    company: Any,
    *,
    esef: EsefClient,
    http: httpx.AsyncClient,
) -> tuple[IssuerIdentity | None, str]:
    """LEI del emisor de ``company`` con su prueba de identidad, o (None, motivo)."""
    isin = _company_isin(company)
    if isin:
        from app.services.listing_identity import reviewed_listing

        listing = reviewed_listing(isin)
        ticker = (getattr(company, "ticker", None) or "").strip().upper()
        if listing is not None and listing.ticker != ticker:
            # El ISIN es de un listado revisado con OTRO ticker (prod: «BFIT»
            # en USD con el ISIN de Basic-Fit, homonimo del BFIT de EE. UU.):
            # esta ficha es otra linea; los hechos del emisor van a la suya.
            return None, f"listado_distinto: el ISIN {isin} es de {listing.ticker}, no de {ticker}"
        try:
            rows = await gleif_lei_records(http, {"filter[isin]": isin})
        except (httpx.HTTPError, ValueError) as exc:
            return None, f"gleif_error: {type(exc).__name__}"
        records = [r for r in (_record(row) for row in rows) if r]
        if len(records) == 1:
            lei, name, _, _ = records[0]
            return IssuerIdentity(lei=lei, legal_name=name, method="isin_gleif", isin=isin), "ok"
        if len(records) > 1:
            return None, f"isin_ambiguo: {len(records)} LEI para {isin}"
        # ISIN sin LEI en GLEIF: se prueba por nombre.

    if _placeholder_name(company):
        return None, "sin_isin_ni_nombre: la ficha solo tiene el ticker como nombre"
    from app.services.financial_ingestion_service import _name_identity_ok

    jurisdiction = SUFFIX_JURISDICTION.get(_ticker_suffix(company.ticker))
    params: dict[str, Any] = {"filter[fulltext]": company.name, "page[size]": 10}
    if jurisdiction:
        params["filter[entity.jurisdiction]"] = jurisdiction
    try:
        rows = await gleif_lei_records(http, params)
    except (httpx.HTTPError, ValueError) as exc:
        return None, f"gleif_error: {type(exc).__name__}"
    candidates = [
        r for r in (_record(row) for row in rows)
        if r and r[3] in {"ISSUED", "LAPSED", "PENDING_TRANSFER", "PENDING_ARCHIVAL", ""}
        and _name_identity_ok(company.name, r[1])
    ]
    with_filings: list[tuple[str, str]] = []
    for lei, name, _, _ in candidates:
        try:
            if await esef.list_filings_for_lei(lei):
                with_filings.append((lei, name))
        except EsefError as exc:
            return None, f"esef_error: {type(exc).__name__}"
    if len(with_filings) == 1:
        lei, name = with_filings[0]
        return IssuerIdentity(lei=lei, legal_name=name, method="name_gleif"), "ok"
    if len(with_filings) > 1:
        return None, f"nombre_ambiguo: {len(with_filings)} emisores con filings para {company.name!r}"
    return None, "sin_emisor_esef: ningun LEI con filings en el indice para este nombre/ISIN"


async def fetch_live_snapshot(
    company: Any,
    *,
    esef: EsefClient | None = None,
    http: httpx.AsyncClient | None = None,
    max_filings: int = 5,
) -> tuple[dict[str, Any] | None, str]:
    """Snapshot ESEF del emisor (misma forma que build_esef_snapshots) o (None, motivo)."""
    own_http = http is None
    http = http or gleif_http_client()
    esef = esef or EsefClient()
    try:
        identity, reason = await resolve_issuer(company, esef=esef, http=http)
        if identity is None:
            return None, reason
        try:
            filings = await esef.list_filings_for_lei(identity.lei)
        except EsefError as exc:
            return None, f"esef_error: {type(exc).__name__}"
        chosen = filings_per_lei(filings, max_filings).get(identity.lei, [])
        if not chosen:
            return None, f"sin_filings_json: LEI {identity.lei} sin render xBRL-JSON en el indice"
        normalized: list[dict[str, Any]] = []
        for filing in chosen:
            try:
                normalized.append(normalize_xbrl_json(await esef.fetch_filing_json(filing)))
            except EsefError as exc:
                # Un ejercicio ilegible no tumba los demas; queda contado.
                logger.info("filing %s ilegible: %s", filing.fxo_id, type(exc).__name__)
        if not normalized:
            return None, "filings_ilegibles"
        latest = chosen[0]
        try:
            entity_name = await esef.get_entity_name(identity.lei)
        except EsefError:
            entity_name = identity.legal_name
        return (
            {
                "lei": identity.lei,
                "ticker": company.ticker.upper(),
                "entity_name": entity_name or identity.legal_name,
                "period_end": latest.period_end,
                "periods": [f.period_end for f in chosen],
                "fxo_id": latest.fxo_id,
                "sha256": latest.sha256,
                "fetched_at": datetime.now(UTC).isoformat(),
                "facts": merge_facts(normalized),
                "origin": "live",
                "source": LIVE_SOURCE,
                "identity": {
                    "method": identity.method,
                    "isin": identity.isin,
                    "legal_name": identity.legal_name,
                },
            },
            "ok",
        )
    finally:
        if own_http:
            await http.aclose()


def reporting_currency(facts: dict[str, Any], default: str = "EUR") -> str:
    """Divisa de presentacion del filing: la iso4217 mas usada en ifrs-full monetarios.

    El mapa ESEF de la app nacio para emisores en EUR; un emisor nordico o
    britanico presenta en SEK/DKK/GBP y con EUR fijo sus hechos se perdian
    enteros (o, peor, se etiquetaban EUR).
    """
    counts: dict[str, int] = {}
    for concept, units in (facts or {}).items():
        if not str(concept).startswith("ifrs-full:") or not isinstance(units, dict):
            continue
        for unit, entries in units.items():
            u = str(unit)
            if u.startswith("iso4217:") and "/" not in u:
                counts[u.split(":", 1)[1]] = counts.get(u.split(":", 1)[1], 0) + len(entries or [])
    if not counts:
        return default
    return max(sorted(counts), key=lambda k: counts[k])
