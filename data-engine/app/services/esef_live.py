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
    ESEF_BASE_URL,
    EsefClient,
    EsefError,
    filings_per_lei,
    gleif_http_client,
    gleif_lei_records,
    merge_facts,
    normalize_xbrl_json,
)
from app.services.connectors.fca_nsm import (
    ANNUAL_REPORT_TYPE,
    NSM_SOURCE,
    NsmClient,
    NsmError,
    tagged_annual_reports,
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
    method: str  # "isin_gleif" | "name_gleif" | "name_gleif_cross_border"
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
    nsm: NsmClient | None = None,
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
    cross_border = False
    if jurisdiction and not rows:
        # The venue country need not be the issuer's legal domicile. Only
        # broaden an empty search, and require the COMPLETE legal name:
        # token overlap could silently choose a subsidiary or a homonym.
        from app.services.cnmv_mapping import _normalize

        global_params = {"filter[entity.legalName]": company.name, "page[size]": 10}
        try:
            global_rows = await gleif_lei_records(http, global_params)
        except (httpx.HTTPError, ValueError) as exc:
            return None, f"gleif_error: {type(exc).__name__}"
        if len(global_rows) >= 10:
            # The helper exposes one page only. A full page cannot prove
            # uniqueness: unseen homonyms must not be silently discarded.
            return None, "nombre_ambiguo: busqueda global de nombre legal sin exhaustividad"
        rows = [row for row in global_rows if (record := _record(row))
                and _normalize(company.name) == _normalize(record[1])]
        cross_border = True
    candidates = [
        r for r in (_record(row) for row in rows)
        if r and r[3] in {"ISSUED", "LAPSED", "PENDING_TRANSFER", "PENDING_ARCHIVAL", ""}
        and _name_identity_ok(company.name, r[1])
    ]
    with_filings: list[tuple[str, str]] = []
    uk_listing = jurisdiction == "GB"
    for lei, name, _, _ in candidates:
        try:
            if await esef.list_filings_for_lei(lei):
                with_filings.append((lei, name))
                continue
        except EsefError as exc:
            return None, f"esef_error: {type(exc).__name__}"
        if uk_listing and nsm is not None:
            # El indice no tiene a todas las emisoras britanicas (Georgia
            # Capital PLC: 0 entidades). Su informe anual depositado en el
            # NSM de la FCA prueba igual que el LEI es de un emisor cotizado.
            try:
                if await nsm.list_filings_for_lei(lei):
                    with_filings.append((lei, name))
            except NsmError:
                pass
    if len(with_filings) == 1:
        lei, name = with_filings[0]
        return IssuerIdentity(
            lei=lei, legal_name=name,
            method="name_gleif_cross_border" if cross_border else "name_gleif",
        ), "ok"
    if len(with_filings) > 1:
        return None, f"nombre_ambiguo: {len(with_filings)} emisores con filings para {company.name!r}"
    return None, "sin_emisor_esef: ningun LEI con filings en el indice (ni en el NSM de la FCA) para este nombre/ISIN"


def _nsm_applies(company: Any, index_filings: list[Any]) -> bool:
    """El NSM (FCA) solo guarda emisoras con valores en mercados del Reino
    Unido: se consulta para un ticker de Londres, para un emisor cuyo indice
    ya es britanico (country GB) o cuando el indice no tiene nada."""
    if SUFFIX_JURISDICTION.get(_ticker_suffix(getattr(company, "ticker", "") or "")) == "GB":
        return True
    if not any(getattr(f, "json_url", None) for f in index_filings):
        return True
    return any(str(getattr(f, "country", "") or "").upper() == "GB" for f in index_filings)


async def fetch_live_snapshot(
    company: Any,
    *,
    esef: EsefClient | None = None,
    http: httpx.AsyncClient | None = None,
    nsm: NsmClient | None = None,
    max_filings: int = 5,
) -> tuple[dict[str, Any] | None, str]:
    """Snapshot ESEF del emisor (misma forma que build_esef_snapshots) o (None, motivo).

    Dos fuentes oficiales y gratuitas, por LEI:
    1. filings.xbrl.org (render xBRL-JSON) — UE/EEE y parte del Reino Unido;
    2. el NSM de la FCA (paquete ESEF/UKSEF con iXBRL, ``connectors.fca_nsm``)
       para emisoras del Reino Unido: completa los ejercicios que el indice
       aun no tiene (ABF FY2026, depositado el 2026-11-05) o que no tiene
       nunca. Si un ejercicio esta en las dos, gana el indice (ya validado).
    ``filing_sources`` guarda, por ejercicio, la URL del documento, su fecha
    de deposito y su sha256: cada hecho es citable."""
    own_http = http is None
    http = http or gleif_http_client()
    esef = esef or EsefClient()
    # Mismo cliente HTTP que GLEIF (URLs absolutas): en tests comparte el
    # MockTransport y nunca sale a red.
    nsm = nsm or NsmClient(client=http)
    try:
        identity, reason = await resolve_issuer(company, esef=esef, http=http, nsm=nsm)
        if identity is None:
            return None, reason
        try:
            filings = await esef.list_filings_for_lei(identity.lei)
        except EsefError as exc:
            return None, f"esef_error: {type(exc).__name__}"
        chosen = filings_per_lei(filings, max_filings).get(identity.lei, [])
        nsm_filings: list[Any] = []
        nsm_note = ""
        if _nsm_applies(company, filings):
            try:
                nsm_all = await nsm.list_filings_for_lei(identity.lei)
            except NsmError as exc:
                nsm_all = []
                nsm_note = f"nsm_error: {exc}"
            index_periods = {f.period_end for f in chosen}
            nsm_filings = [f for f in tagged_annual_reports(nsm_all, max_filings) if f.period_end not in index_periods]
            if not nsm_filings and not chosen:
                annual = [f for f in nsm_all if f.filing_type == ANNUAL_REPORT_TYPE]
                if annual:
                    latest_doc = max(annual, key=lambda f: f.submitted_date)
                    nsm_note = (
                        f"nsm_sin_etiquetar: {len(annual)} informes anuales en el NSM de la FCA, "
                        f"ninguno con iXBRL (ultimo {latest_doc.submitted_date}, "
                        f"{latest_doc.document_format}: {latest_doc.url})"
                    )
        # Ejercicios mas recientes primero; en empate, el indice.
        plan: list[tuple[str, int, Any]] = [(f.period_end or "", 0, f) for f in chosen]
        plan += [(f.period_end or "", 1, f) for f in nsm_filings]
        plan.sort(key=lambda row: (row[0], -row[1]), reverse=True)
        selected: list[tuple[str, int, Any]] = []
        for row in plan:
            if len(selected) >= max_filings or any(r[0] == row[0] for r in selected):
                continue
            selected.append(row)
        if not selected:
            if nsm_note:
                return None, nsm_note
            return None, f"sin_filings_json: LEI {identity.lei} sin render xBRL-JSON en el indice"
        normalized: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        for period_end, kind, filing in selected:
            try:
                if kind == 0:
                    normalized.append(normalize_xbrl_json(await esef.fetch_filing_json(filing)))
                    sources.append({
                        "period_end": period_end, "origin": "filings.xbrl.org",
                        "url": ESEF_BASE_URL + str(filing.json_url),
                        "fxo_id": filing.fxo_id, "sha256": filing.sha256,
                    })
                else:
                    got = await nsm.fetch_tagged_facts(filing)
                    normalized.append(got["facts"])
                    sources.append({
                        "period_end": period_end, "origin": "fca_nsm",
                        "url": got["source_url"], "submitted_date": got["submitted_date"],
                        "fxo_id": f"NSM-{got['disclosure_id']}", "sha256": got["sha256"],
                        "report_path": got["report_path"],
                    })
            except (EsefError, NsmError) as exc:
                # Un ejercicio ilegible no tumba los demas; queda contado.
                logger.info("filing %s ilegible: %s", period_end, exc)
        if not normalized:
            return None, "filings_ilegibles"
        latest = sources[0]
        merged = merge_facts(normalized)
        extension_map = await _extension_map(esef, [row for row in selected if row[1] == 0][:1], merged)
        entity_name = identity.legal_name
        if chosen:
            try:
                entity_name = await esef.get_entity_name(identity.lei) or identity.legal_name
            except EsefError:
                entity_name = identity.legal_name
        origins = {src["origin"] for src in sources}
        source_label = " + ".join(
            label for origin, label in (("filings.xbrl.org", LIVE_SOURCE), ("fca_nsm", NSM_SOURCE)) if origin in origins
        )
        return (
            {
                "lei": identity.lei,
                "ticker": company.ticker.upper(),
                "entity_name": entity_name or identity.legal_name,
                "period_end": latest["period_end"],
                "periods": [src["period_end"] for src in sources],
                "fxo_id": latest["fxo_id"],
                "sha256": latest["sha256"],
                "fetched_at": datetime.now(UTC).isoformat(),
                "facts": merged,
                **({"extension_map": extension_map} if extension_map else {}),
                "origin": "live",
                "source": source_label,
                "filing_sources": sources,
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


ESEF_EXTENSION_METRICS = ("capital_expenditure", "financial_liabilities_noncurrent", "financial_liabilities_current")
_LEASE_PARTS = {
    "financial_liabilities_noncurrent": "ifrs-full:NoncurrentLeaseLiabilities",
    "financial_liabilities_current": "ifrs-full:CurrentLeaseLiabilities",
}


def _metrics_without_standard(facts: dict[str, Any]) -> list[str]:
    """Métricas ESEF objetivo sin NINGÚN hecho de sus conceptos estándar (alias o partes)."""
    from app.services.financial_ingestion_service import (
        ESEF_METRIC_MAP,
        ESEF_PART_CONCEPTS,
        ESEF_SUPERSET_CONCEPTS,
    )

    concepts = {metric: set(c) for metric, c, _unit in ESEF_METRIC_MAP}
    out: list[str] = []
    for metric in ESEF_EXTENSION_METRICS:
        known = concepts.get(metric, set()) | set(ESEF_PART_CONCEPTS.get(metric, [])) | set(
            ESEF_SUPERSET_CONCEPTS.get(metric, []))
        if not any(any(not e.get("dims") for es in (facts.get(c) or {}).values() for e in es) for c in known):
            out.append(metric)
    return out


async def _extension_map(esef: Any, latest: list[tuple[str, int, Any]], facts: dict[str, Any]) -> dict[str, Any]:
    """Conceptos propios del emisor que equivalen a métricas sin concepto estándar (``xbrl_extension_map``).

    Lee la taxonomía del paquete del último ejercicio del índice. Nunca lanza:
    sin paquete o ilegible no hay mapa (las métricas siguen N/D como hoy)."""
    from app.services import xbrl_extension_map as xm

    wanted = _metrics_without_standard(facts)
    if not wanted or not latest or not hasattr(esef, "fetch_package"):
        return {}
    filing = latest[0][2]
    try:
        tax = xm.taxonomy_from_package(await esef.fetch_package(filing))
    except Exception as exc:  # noqa: BLE001 - paquete ausente o ilegible: N/D con motivo
        motivo = f"taxonomía de extensión no legible ({type(exc).__name__})"
        return {m: xm.NotAvailable(m, motivo).as_dict() for m in wanted}
    out: dict[str, Any] = {}
    for metric, res in xm.resolve_extensions(tax, xm.facts_from_xbrl_json(facts), metrics=wanted).items():
        row = res.as_dict()
        lease = _LEASE_PARTS.get(metric)
        if isinstance(res, xm.ExtensionMapping) and lease and lease in tax.narrower.get(res.concept, set()):
            if any(not e.get("dims") for es in (facts.get(lease) or {}).values() for e in es):
                row = xm.NotAvailable(metric, (
                    f"{res.concept} incluye arrendamientos ({lease}) que el emisor también declara aparte: "
                    "se contarían dos veces")).as_dict()
            else:
                row["includes_leases"] = True
        row.pop("values", None)
        row["source"] = ESEF_BASE_URL + str(getattr(filing, "package_url", "") or "")
        out[metric] = row
    return out


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
