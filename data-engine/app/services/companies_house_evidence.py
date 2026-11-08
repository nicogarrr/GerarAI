"""Grupo britanico de un holding y sus cuentas depositadas en Companies House.

Para el desglose por partes (SOTP) de un holding con filiales britanicas que no
cotizan, y como respaldo de los informes de un emisor britanico. Todo es general
(nunca por emisor) y cada dato lleva su URL publica de Companies House.

Como se decide quien es del grupo (sin adivinar por el nombre):
1. Raiz por nombre EXACTO: la sociedad cuyo nombre normalizado coincide con el
   del holding (``Georgia Capital PLC`` -> GEORGIA CAPITAL PLC, 10852406).
2. Pistas (nombres de segmentos o filiales que ya tiene la evidencia, p. ej.
   «Brit» en Fairfax): cada candidata solo entra si su cadena de PSC (quien la
   controla, segun Companies House) sube hasta una sociedad ya verificada o hasta
   una controladora cuyo nombre lleva el nombre propio del holding (BRIT
   INSURANCE HOLDINGS -> BRIT GROUP HOLDINGS -> FAIRFAX UK HOLDINGS). El nombre
   de la candidata por si solo NO basta (hay un «FAIRFAX LTD» que no es Fairfax).
3. Expansion: los administradores en activo de las sociedades verificadas
   llevan a otras sociedades; entran las que tienen como PSC a una verificada.

Cifras: solo de cuentas en iXBRL (las pequeñas y medianas suelen ir asi), con el
parser iXBRL que ya usa ESEF: ingresos, patrimonio neto y resultado del periodo
mas reciente, consolidado (sin ejes). Las cuentas en PDF (las grandes; Companies
House las guarda escaneadas) se citan con su enlace, fecha y paginas, sin cifras.
"""

from __future__ import annotations

import io
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.connectors.companies_house import (
    IXBRL_MIME,
    CompaniesHouseClient,
    CompaniesHouseError,
    normalize_company_number,
    public_company_url,
    public_document_url,
)

MAX_CHAIN_HOPS = 4
MAX_HINTS = 12
MATCHES_PER_HINT = 3
MAX_EXPAND_MEMBERS = 5
MAX_OFFICERS_PER_MEMBER = 6
MAX_CANDIDATES = 30
DEFAULT_MAX_MEMBERS = 15

_SUFFIXES = (
    ("PUBLIC LIMITED COMPANY", "PLC"), ("LIMITED", "LTD"), ("INCORPORATED", "INC"),
    ("CORPORATION", "CORP"), ("COMPANY", "CO"),
)
#: Palabras que no identifican a un grupo (no sirven como «nombre propio»).
_GENERIC = frozenset({
    "THE", "GROUP", "HOLDINGS", "HOLDING", "CAPITAL", "FINANCIAL", "INTERNATIONAL", "GLOBAL", "UK",
    "PLC", "LTD", "INC", "CORP", "CO", "LLP", "SE", "NV", "SA", "AG", "AND", "OF", "INVESTMENTS",
    "INVESTMENT", "PARTNERS", "SERVICES", "COMPANY", "TRUST", "FUND", "BANK", "INSURANCE",
})
_UK_PLACES = ("ENGLAND", "WALES", "SCOTLAND", "UNITED KINGDOM", "NORTHERN IRELAND", "COMPANIES HOUSE", "UK")
_INACTIVE = frozenset({"dissolved", "converted-closed", "closed", "removed"})

#: Conceptos iXBRL (nombre local; el prefijo cambia entre taxonomias FRC: core, frs-core, uk-core, d…).
FIGURE_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": ("TurnoverRevenue", "Revenue"),
    "net_assets": ("NetAssetsLiabilities", "Equity"),
    "profit": ("ProfitLoss", "ProfitLossForPeriod"),
    "profit_before_tax": ("ProfitLossOnOrdinaryActivitiesBeforeTax", "ProfitLossBeforeTax"),
}
FIGURE_LABELS = {
    "revenue": "ingresos (turnover)",
    "net_assets": "patrimonio neto",
    "profit": "resultado del ejercicio",
    "profit_before_tax": "resultado antes de impuestos",
}


def normalize_name(raw: Any) -> str:
    text = re.sub(r"[^A-Z0-9&]+", " ", str(raw or "").upper()).strip()
    text = re.sub(r"^THE ", "", text)
    for long, short in _SUFFIXES:
        text = re.sub(rf"\b{long}\b", short, text)
    return " ".join(text.split())


def distinctive_token(name: Any) -> str | None:
    """Primera palabra propia del nombre (FAIRFAX de «Fairfax Financial Holdings Ltd»)."""
    for word in normalize_name(name).split():
        if word not in _GENERIC and len(word) >= 4 and not word.isdigit():
            return word
    return None


@dataclass
class GroupMember:
    number: str
    name: str
    depth: int
    via: str
    parent: str | None = None
    status: str | None = None


@dataclass
class _Walk:
    client: CompaniesHouseClient
    token: str | None
    members: dict[str, GroupMember] = field(default_factory=dict)
    psc_cache: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    async def pscs(self, number: str) -> list[dict[str, Any]]:
        if number not in self.psc_cache:
            rows = await self.client.persons_with_significant_control(number)
            self.psc_cache[number] = [r for r in rows if not r.get("ceased_on") and not r.get("ceased")]
        return self.psc_cache[number]


def _has_token(name: Any, token: str | None) -> bool:
    return bool(token) and token in normalize_name(name).split()


def _hint_match(item: dict[str, Any], key: str) -> bool:
    """La pista es el comienzo del nombre actual o de uno anterior (``snippet`` de la busqueda)."""
    names = [item.get("title")] + str(item.get("snippet") or "").split("\u00b7")
    return any((normalize_name(n) + " ").startswith(key + " ") for n in names if n)


def _corporate(psc: dict[str, Any]) -> bool:
    kind = str(psc.get("kind") or "")
    return "corporate-entity" in kind or "legal-person" in kind


def _uk_registered(psc: dict[str, Any]) -> str | None:
    ident = psc.get("identification") or {}
    where = " ".join(str(ident.get(k) or "") for k in ("country_registered", "place_registered")).upper()
    if not any(place in where for place in _UK_PLACES):
        return None
    return normalize_company_number(ident.get("registration_number"))


async def _verify_chain(walk: _Walk, number: str, name: str, via: str) -> bool:
    """Sube por los PSC corporativos hasta una verificada o hasta el nombre propio del holding."""
    chain: list[tuple[str, str]] = [(number, name)]
    current = number
    for _ in range(MAX_CHAIN_HOPS):
        corporate = [p for p in await walk.pscs(current) if _corporate(p)]
        next_hop: tuple[str, str] | None = None
        for psc in corporate:
            reg = _uk_registered(psc)
            if reg and reg in walk.members:
                _add_chain(walk, chain, walk.members[reg], via)
                return True
        for psc in corporate:
            psc_name = str(psc.get("name") or "")
            if walk.token and walk.token in normalize_name(psc_name).split():
                reg = _uk_registered(psc)
                if reg:
                    top = GroupMember(reg, psc_name, 0, f"controladora con el nombre del holding ({psc_name})")
                    walk.members.setdefault(reg, top)
                    _add_chain(walk, chain, walk.members[reg], via)
                else:
                    top_number = chain[-1][0]
                    walk.members.setdefault(top_number, GroupMember(
                        top_number, chain[-1][1], 0, f"su PSC es {psc_name}, con el nombre del holding"))
                    _add_chain(walk, chain[:-1], walk.members[top_number], via)
                return True
            reg = _uk_registered(psc)
            if reg and next_hop is None:
                next_hop = (reg, psc_name)
        if next_hop is None or any(n == next_hop[0] for n, _ in chain):
            return False
        chain.append(next_hop)
        current = next_hop[0]
    return False


def _add_chain(walk: _Walk, chain: list[tuple[str, str]], top: GroupMember, via: str) -> None:
    """Da de alta la cadena de abajo arriba bajo ``top`` (profundidad creciente hacia la candidata)."""
    parent = top
    for number, name in reversed(chain):
        if number in walk.members:
            parent = walk.members[number]
            continue
        member = GroupMember(number, name, parent.depth + 1, f"PSC: {parent.name} ({parent.number}); {via}",
                             parent=parent.number)
        walk.members[number] = member
        parent = member


async def discover_group(client: CompaniesHouseClient, *, holding_name: str, hints: list[str] | tuple[str, ...] = (),
                         max_members: int = DEFAULT_MAX_MEMBERS) -> tuple[list[GroupMember], str]:
    """(miembros verificados, motivo). Orden: profundidad y numero (determinista)."""
    walk = _Walk(client=client, token=distinctive_token(holding_name))
    target = normalize_name(holding_name)
    if target:
        for item in await client.search_companies(holding_name, items=10):
            number = normalize_company_number(item.get("company_number"))
            if number and normalize_name(item.get("title")) == target and item.get("company_status") not in _INACTIVE:
                walk.members[number] = GroupMember(number, str(item.get("title")), 0, "nombre exacto del holding",
                                                   status=item.get("company_status"))
                break
    seen_hints: set[str] = set()
    for hint in hints:
        key = normalize_name(hint)
        if not key or key in seen_hints or key == target or len(key) < 3:
            continue
        seen_hints.add(key)
        if len(seen_hints) > MAX_HINTS:
            break
        matches = [it for it in await client.search_companies(hint, items=50)
                   if it.get("company_status") not in _INACTIVE and _hint_match(it, key)]
        # Primero las que llevan el nombre propio del holding, luego las de cabecera (GROUP/HOLDINGS).
        matches.sort(key=lambda it: (not _has_token(it.get("title"), walk.token),
                                     not ({"GROUP", "HOLDINGS"} & set(normalize_name(it.get("title")).split()))))
        for item in matches[:MATCHES_PER_HINT]:
            number = normalize_company_number(item.get("company_number"))
            if not number or number in walk.members:
                continue
            if _has_token(item.get("title"), walk.token):
                # Dos señales: responde a la pista (nombre actual o anterior) y lleva el nombre del holding.
                walk.members[number] = GroupMember(number, str(item.get("title")), 0,
                                                   f"pista «{hint}» y nombre del holding",
                                                   status=item.get("company_status"))
                continue
            await _verify_chain(walk, number, str(item.get("title")), f"pista «{hint}»")
    if not walk.members:
        return [], "sin_sociedad_britanica: ni el nombre exacto ni las pistas llevan a una sociedad verificada"

    candidates: dict[str, str] = {}
    expanded: set[str] = set()
    while len(expanded) < MAX_EXPAND_MEMBERS:
        pending = sorted((m for m in walk.members.values() if m.number not in expanded),
                         key=lambda m: (m.depth, m.number))
        if not pending:
            break
        member = pending[0]
        expanded.add(member.number)
        officers = [o for o in await client.officers(member.number) if not o.get("resigned_on")]
        for officer in officers[:MAX_OFFICERS_PER_MEMBER]:
            path = ((officer.get("links") or {}).get("officer") or {}).get("appointments")
            if not path:
                continue
            for appt in await client.officer_appointments(str(path)):
                to = appt.get("appointed_to") or {}
                number = normalize_company_number(to.get("company_number"))
                if (number and number not in walk.members and not appt.get("resigned_on")
                        and to.get("company_status") not in _INACTIVE and len(candidates) < MAX_CANDIDATES):
                    candidates.setdefault(number, str(to.get("company_name") or number))
        # Verificacion por PSC: entra la candidata cuya cadena de controladoras llega al grupo.
        for number, name in sorted(candidates.items()):
            if number not in walk.members:
                await _verify_chain(walk, number, name, "administrador comun")
    members = sorted(walk.members.values(), key=lambda m: (m.depth, m.number))[:max_members]
    return members, "ok"


def _accounts_type(description: str) -> str:
    match = re.search(r"accounts-type-([a-z-]+)", description or "")
    return match.group(1) if match else (description or "")


def _local(concept: str) -> str:
    return concept.rsplit(":", 1)[-1]


def figures_from_ixbrl(content: bytes) -> list[dict[str, Any]]:
    """Cifras del periodo mas reciente (consolidado, sin ejes) de unas cuentas iXBRL."""
    from app.services.connectors.esef_ixbrl import parse_ixbrl_facts

    parsed = parse_ixbrl_facts(io.BytesIO(content))
    by_local: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for concept, units in (parsed.get("facts") or {}).items():
        for unit, entries in units.items():
            if not str(unit).startswith("iso4217:"):
                continue
            for entry in entries:
                if not entry.get("dims"):
                    by_local.setdefault(_local(concept), []).append((concept, unit, entry))
    out: list[dict[str, Any]] = []
    for metric, names in FIGURE_CONCEPTS.items():
        for name in names:
            rows = by_local.get(name) or []
            if not rows:
                continue
            concept, unit, entry = max(rows, key=lambda r: (r[2].get("end") or r[2].get("instant") or "",
                                                            r[2].get("start") or ""))
            try:
                value = Decimal(str(entry["val"]))
            except (InvalidOperation, KeyError):
                continue
            out.append({
                "metric": metric, "label": FIGURE_LABELS[metric], "value": float(value),
                "value_millions": round(float(value) / 1e6, 6), "currency": unit.split(":", 1)[1],
                "period_start": entry.get("start"), "period_end": entry.get("end") or entry.get("instant"),
                "concept": concept,
            })
            break
    return out


async def latest_accounts(client: CompaniesHouseClient, member: GroupMember) -> dict[str, Any] | None:
    """Ultimas cuentas depositadas de una sociedad, con enlace citable y cifras si van en iXBRL."""
    items = await client.filing_history(member.number, category="accounts", items=10)
    filed = [it for it in items if str(it.get("description") or "").startswith("accounts-with")]
    if not filed:
        return None
    last = max(filed, key=lambda it: str(it.get("date") or ""))
    tx = str(last.get("transaction_id") or "")
    if not tx:
        self_link = str((last.get("links") or {}).get("self") or "")
        tx = self_link.rstrip("/").rsplit("/", 1)[-1]
    out: dict[str, Any] = {
        "company_number": member.number, "company_name": member.name, "depth": member.depth,
        "parent": member.parent, "via": member.via, "company_url": public_company_url(member.number),
        "filed_on": last.get("date"), "made_up_to": (last.get("description_values") or {}).get("made_up_date"),
        "accounts_type": _accounts_type(str(last.get("description") or "")),
        "document_url": public_document_url(member.number, tx) if tx else public_company_url(member.number),
        "formats": [], "pages": None, "figures": [],
    }
    meta_url = (last.get("links") or {}).get("document_metadata")
    if not meta_url:
        return out
    meta = await client.document_metadata(str(meta_url))
    if not meta:
        return out
    out["formats"] = sorted((meta.get("resources") or {}).keys())
    out["pages"] = meta.get("pages")
    if IXBRL_MIME in out["formats"]:
        out["ixbrl_url"] = public_document_url(member.number, tx, fmt="xhtml") if tx else None
        try:
            out["figures"] = figures_from_ixbrl(await client.document_content(meta, IXBRL_MIME))
        except (CompaniesHouseError, ValueError, SyntaxError) as exc:
            out["figures_error"] = type(exc).__name__
    elif PDF_MIME in out["formats"] and tx:
        attach_scanned_figures(out)
    return out


PDF_MIME = "application/pdf"
#: Etiquetas de las cifras leidas de las cuentas escaneadas (estados primarios).
SCANNED_LABELS = {
    "revenue": "ingresos / primas", "profit_before_tax": "resultado antes de impuestos",
    "profit_for_year": "resultado del ejercicio", "profit_attributable": "resultado atribuible",
    "total_equity": "patrimonio total", "equity_attributable": "patrimonio atribuible",
    "net_assets": "activos netos (NAV)", "cash": "caja y equivalentes", "borrowings": "deuda financiera",
}


def attach_scanned_figures(row: dict[str, Any]) -> None:
    """Cifras con pagina de unas cuentas en PDF escaneado, si el worker ya las leyo (cache).

    Sin lectura: ``scanned.status = pending`` (la encola :func:`queue_scanned_reads`)."""
    from app.services import scanned_accounts

    cached = scanned_accounts.load_cached(str(row["company_number"]), row.get("made_up_to"))
    if not cached:
        row["scanned"] = {"status": "pending"}
        return
    doc = row.get("document_url")
    row["scanned"] = {"status": cached.get("status"), "reason": cached.get("reason"),
                      "checks": cached.get("checks"), "statements": cached.get("statements"),
                      "rejected": [{"metric": f.get("metric"), "page": f.get("page"), "reason": f.get("reason")}
                                   for f in cached.get("rejected") or []]}
    row["figures"] = [
        {"metric": f["metric"], "label": SCANNED_LABELS.get(f["metric"], f["metric"]), "value": f["value"],
         "value_millions": f.get("value_millions"), "currency": f.get("currency"), "unit": f.get("unit"),
         "period_end": f.get("period_end"), "concept": f"pág. {f['page']}: «{f['label']}»",
         "page": f.get("page"), "line": f.get("line"), "basis": f.get("basis"), "check": f.get("check"),
         "page_url": scanned_accounts.page_url(doc, f.get("page")), "source": "ocr"}
        for f in cached.get("figures") or [] if f.get("value") is not None
    ]


def scanned_targets(result: dict[str, Any] | None, *, limit: int = 3) -> list[dict[str, Any]]:
    """Cuentas en PDF escaneado que merece la pena leer: las del propio emisor (nombre exacto)
    y las consolidadas de sus filiales (:func:`subsidiary_reports`)."""
    rows = [m for m in (result or {}).get("members") or [] if m.get("via") == "nombre exacto del holding"]
    rows += subsidiary_reports(result or {}, limit=limit)
    return [m for m in rows if (m.get("scanned") or {}).get("status") == "pending" and m.get("document_url")][:limit]


def queue_scanned_reads(result: dict[str, Any] | None, ticker: str | None) -> int:
    """Encola (una vez) la lectura OCR de las cuentas escaneadas del grupo; devuelve cuantas."""
    from app.services import scanned_accounts

    sent = 0
    for row in scanned_targets(result):
        number, made_up = str(row["company_number"]), row.get("made_up_to")
        if not scanned_accounts.claim_pending(number, made_up):
            continue
        try:
            from app.workers.dramatiq_app import extract_scanned_accounts

            extract_scanned_accounts.send(number, made_up, str(row["document_url"]),
                                          str(row.get("company_name") or ""), ticker)
            sent += 1
        except Exception:  # noqa: BLE001 - sin broker la cuenta queda pendiente
            continue
    return sent


async def group_accounts(client: CompaniesHouseClient, *, holding_name: str, hints: list[str] | tuple[str, ...] = (),
                         max_members: int = DEFAULT_MAX_MEMBERS) -> dict[str, Any]:
    """{status, reason, members:[cuentas de cada sociedad verificada], requests_used}."""
    try:
        members, reason = await discover_group(client, holding_name=holding_name, hints=hints,
                                               max_members=max_members)
    except CompaniesHouseError as exc:
        return {"status": "error", "reason": type(exc).__name__, "members": [], "requests_used": client.requests_used}
    rows: list[dict[str, Any]] = []
    status = "ok" if members else "empty"
    for member in members:
        try:
            accounts = await latest_accounts(client, member)
        except CompaniesHouseError as exc:  # presupuesto o fallo puntual: lo hecho se conserva
            status, reason = "partial", type(exc).__name__
            break
        rows.append(accounts or {**asdict(member), "company_number": member.number, "company_name": member.name,
                                 "company_url": public_company_url(member.number), "figures": [],
                                 "accounts_type": None})
    return {"status": status, "reason": reason, "members": rows, "requests_used": client.requests_used}


# -- uso sincrono con cache por proceso --------------------------------------------
CACHE_TTL_S = 12 * 3600
_CACHE: dict[tuple[str, tuple[str, ...]], tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()


def collect_group_accounts(holding_name: str, hints: list[str] | tuple[str, ...] = (), *,
                           client: CompaniesHouseClient | None = None) -> dict[str, Any] | None:
    """Version sincrona (herramientas del SOTP). None si la funcion esta apagada (sin clave)."""
    from app.services.connectors.companies_house import client_from_settings

    key = (normalize_name(holding_name), tuple(sorted({normalize_name(h) for h in hints if h})))
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    if hit and now - hit[0] < CACHE_TTL_S:
        for row in hit[1].get("members") or []:
            if (row.get("scanned") or {}).get("status") == "pending":
                attach_scanned_figures(row)  # el worker pudo terminar la lectura OCR despues
        return hit[1]
    ch = client or client_from_settings()
    if ch is None:
        return None

    async def run() -> dict[str, Any]:
        try:
            return await group_accounts(ch, holding_name=holding_name, hints=list(hints))
        finally:
            if client is None:
                await ch.aclose()

    result = _run_sync(run)
    if result.get("status") in ("ok", "empty"):
        with _CACHE_LOCK:
            _CACHE[key] = (now, result)
    return result


def _run_sync(factory: Any) -> Any:
    from app.services.async_bridge import run_from_any_context

    try:
        return run_from_any_context(factory(), timeout=120)
    except Exception as exc:  # noqa: BLE001 - la herramienta nunca tumba al experto
        return {"status": "error", "reason": type(exc).__name__, "members": [], "requests_used": None}


#: Categorias de impulsores de valor cuyos nombres sirven de pista de filial (segmentos y activos).
HINT_CATEGORIES = ("linea_negocio", "activo", "opcion")


def subsidiary_hints(db: Any, company: Any, tenant_id: int | None) -> list[str]:
    """Nombres de filiales y segmentos que ya tiene GerarAI de la empresa, por este orden:
    filiales verificadas de los alias de datos (Wikidata P355/P749, ``company_alias_sources``)
    y nombres de segmentos/activos de los impulsores de valor del Recopilador."""
    names: list[str] = []
    try:
        from app.services.company_alias_sources import VERIFIED, load_cached

        record = load_cached(db).get(str(company.ticker or "").upper())
        for alias in (record.aliases if record else []):
            if alias.tipo == "filial" and alias.etiqueta == VERIFIED:
                names.append(alias.termino)
    except Exception:  # noqa: BLE001 - sin cache de alias se sigue con los impulsores
        pass
    if type(tenant_id) is int:
        from app.services.value_driver_service import ValueDriverService

        rows = ValueDriverService().current(db, company_id=company.id, tenant_id=tenant_id)
        names.extend(sorted(str(r.name).strip() for r in rows.values()
                            if r.category in HINT_CATEGORIES and str(r.name or "").strip()))
    out: list[str] = []
    for name in names:
        if name and normalize_name(name) not in {normalize_name(n) for n in out}:
            out.append(name)
    return out[:MAX_HINTS]


def subsidiary_reports(result: dict[str, Any], *, limit: int = 2) -> list[dict[str, Any]]:
    """Cuentas de filiales que merece la pena leer enteras: primero las consolidadas
    (``group``: recogen todo lo que cuelga debajo), si no las completas mas arriba en el
    grupo. Nunca las de la propia raiz por nombre exacto (eso es el emisor) ni las durmientes."""
    rows = [m for m in result.get("members") or []
            if m.get("document_url") and m.get("accounts_type") not in (None, "dormant")
            and m.get("via") != "nombre exacto del holding"]
    group = [m for m in rows if m.get("accounts_type") == "group"]
    pool = group or [m for m in rows if m.get("accounts_type") == "full"]
    pool.sort(key=lambda m: (m.get("depth") or 0, -(m.get("pages") or 0), m.get("company_number")))
    return pool[:limit]


async def issuer_annual_accounts(client: CompaniesHouseClient, holding_name: str) -> dict[str, Any] | None:
    """Ultimas cuentas anuales del propio emisor (nombre exacto), o None."""
    target = normalize_name(holding_name)
    for item in await client.search_companies(holding_name, items=10):
        number = normalize_company_number(item.get("company_number"))
        if number and normalize_name(item.get("title")) == target and item.get("company_status") not in _INACTIVE:
            return await latest_accounts(client, GroupMember(number, str(item.get("title")), 0,
                                                             "nombre exacto del emisor"))
    return None


__all__ = [
    "attach_scanned_figures",
    "queue_scanned_reads",
    "scanned_targets",
    "FIGURE_CONCEPTS",
    "GroupMember",
    "collect_group_accounts",
    "discover_group",
    "distinctive_token",
    "figures_from_ixbrl",
    "group_accounts",
    "issuer_annual_accounts",
    "subsidiary_hints",
    "subsidiary_reports",
    "latest_accounts",
    "normalize_name",
]
