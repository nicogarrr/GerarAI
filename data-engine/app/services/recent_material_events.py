"""Hechos materiales recientes de una empresa para su tesis (todas las empresas).

Petición del propietario (3-nov-2026, sobre ASTS): la tesis tiene que llevar
«lo último de lo último» (Brasil, Chile, la compra que quiere hacer SpaceX, el
primer handoff...). Medido en prod ese día: el pipeline de noticias SÍ tenía
los cuatro hechos ligados a ASTS, pero la tesis cogía 5 noticias ordenadas
por «materialidad» antes que por fecha y le salieron titulares de opinión del
8 al 20 de octubre con nota 10; todo lo posterior quedó fuera.

Reglas de este módulo (deterministas, sin modelo, solo lectura de la base):

- Ventana de ``WINDOW_DAYS`` días, de más nuevo a más antiguo.
- Fuentes: 8-K/6-K de la SEC (documentos y filas del pipeline con conector
  SEC), notas de prensa (Business Wire, PR Newswire, GlobeNewswire, ACCESS
  Newswire...), página de inversores de la empresa (documentos IR) y el resto
  del pipeline de noticias con materialidad >= ``MIN_MATERIALITY``.
- La misma historia contada por varios medios cuenta una vez (criterio de
  ``news_story_cluster``); su fecha es la del primer aviso y su fuente la
  primaria (SEC o comunicado) si alguna de las copias lo es.
- Las fuentes primarias tienen hueco garantizado; el resto rellena por fecha.
- Cada hecho lleva fecha y fuente; un hecho sin fecha no entra.
- Regla de vigencia: lo posterior al último informe periódico (10-K/10-Q/
  20-F/40-F) se marca como tal y prevalece; nada anterior a ese informe
  sustituye a un hecho más reciente.
- Lo que no se encuentra no se inventa: cada fuente consultada declara lo que
  encontró o que no encontró nada (y por qué, si se sabe).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

WINDOW_DAYS = 45
MAX_EVENTS = 15
MAX_PRIMARY = 6
FRESH_DAYS = 3
MIN_MATERIALITY = 5
PERIODIC_FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A")
CURRENT_REPORT_FORMS = ("8-K", "8-K/A", "6-K", "6-K/A")

# Agencias de comunicados: lo que llega por ellas lo redacta la empresa (o su
# socio en un comunicado conjunto), no un medio.
_WIRE_RE = re.compile(
    r"business\s*wire|pr\s*newswire|globe\s*newswire|access\s*newswire|accesswire|"
    r"newsfile|cision|notified",
    re.IGNORECASE,
)
_WIRE_DOMAINS = ("businesswire.com", "prnewswire.com", "globenewswire.com", "accessnewswire.com", "newsfilecorp.com")

# Apartados del formulario 8-K (instrucciones oficiales de la SEC).
ITEM_LABELS_8K = {
    "1.01": "acuerdo material",
    "1.02": "fin de un acuerdo material",
    "1.05": "incidente de ciberseguridad",
    "2.01": "compra o venta de activos",
    "2.02": "resultados",
    "2.03": "nueva obligación financiera",
    "2.05": "costes de salida",
    "2.06": "deterioro",
    "3.02": "venta de acciones no registrada",
    "3.03": "cambio en derechos de los accionistas",
    "5.02": "salida o nombramiento de directivos",
    "5.03": "cambio de estatutos",
    "5.07": "votación de accionistas",
    "7.01": "información al mercado (Reg FD)",
    "8.01": "otros hechos relevantes",
    "9.01": "anexos",
}

KIND_SEC = "SEC"
KIND_PRESS = "comunicado"
KIND_IR = "página de inversores"
KIND_NEWS = "noticia"
_PRIMARY_KINDS = {KIND_SEC, KIND_PRESS, KIND_IR}


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def items_label(items: Any) -> str | None:
    """«5.02 salida o nombramiento de directivos; 9.01 anexos» desde "5.02,9.01"."""
    codes = [c.strip() for c in str(items or "").split(",") if c.strip()]
    if not codes:
        return None
    return "; ".join(f"{c} {ITEM_LABELS_8K[c]}" if c in ITEM_LABELS_8K else c for c in codes)


def news_kind(source: str | None, url: str | None, metadata: dict | None) -> str:
    """SEC / comunicado / noticia para una fila del pipeline de noticias."""
    meta = metadata or {}
    tier = ((meta.get("assessment") or {}).get("source_tier") or "").lower()
    if (meta.get("connector") or "").lower() == "sec" or tier in {"tier_1_regulatory", "tier_primary"} or (
        (source or "").strip().upper() == "SEC"
    ):
        return KIND_SEC
    if _WIRE_RE.search(source or "") or any(d in (url or "").lower() for d in _WIRE_DOMAINS):
        return KIND_PRESS
    return KIND_NEWS


def _story_signature(title: str, company_tokens: set[str]) -> set[str]:
    from app.services.news_story_cluster import signature

    return signature(title, company_tokens)


RARE_TOKEN_MAX_SHARE = 0.10
RARE_TOKEN_MIN_POOL = 10
RARE_TOKEN_WINDOW = timedelta(hours=72)


def _rare_tokens(pool: list[dict[str, Any]]) -> set[str]:
    """Tokens que solo salen en pocas noticias de la ventana («brazil»,
    «chile», «handoff»): dos titulares de 72 h que comparten uno cuentan la
    misma historia aunque la redacción cambie. Medido en prod (ASTS, 26-oct a
    3-nov): Brasil llegó por 15 medios con titulares distintos y la regla de
    portada (solape de tokens) solo juntaba 2."""
    from app.services.news_story_cluster import _GENERIC_FINANCE

    if len(pool) < RARE_TOKEN_MIN_POOL:
        return set()
    df: dict[str, int] = {}
    for cand in pool:
        for token in cand["_sig"]:
            df[token] = df.get(token, 0) + 1
    limit = max(3.0, len(pool) * RARE_TOKEN_MAX_SHARE)
    return {
        token
        for token, count in df.items()
        if 2 <= count <= limit and token.isalpha() and len(token) >= 5 and token not in _GENERIC_FINANCE
    }


def _same_story(a: dict, b: dict, rare: set[str]) -> bool:
    from app.services.news_story_cluster import same_story

    if a["_key"] and a["_key"] == b["_key"]:
        return True
    if same_story(a["_sig"], b["_sig"], a["_dt"], b["_dt"]):
        return True
    return abs(a["_dt"] - b["_dt"]) <= RARE_TOKEN_WINDOW and bool(a["_sig"] & b["_sig"] & rare)


def _company_tokens(ticker: str | None, name: str | None) -> set[str]:
    from app.services.news_story_cluster import _TOKEN_RE, _normalize

    tokens: set[str] = set()
    if ticker:
        tokens.add(_normalize(ticker))
    for token in _TOKEN_RE.findall(_normalize(name or "")):
        tokens.add(token)
    return tokens


def select_recent_events(
    candidates: list[dict[str, Any]],
    *,
    now: datetime,
    ticker: str | None = None,
    company_name: str | None = None,
    window_days: int = WINDOW_DAYS,
    limit: int = MAX_EVENTS,
    max_primary: int = MAX_PRIMARY,
    min_materiality: int = MIN_MATERIALITY,
) -> list[dict[str, Any]]:
    """Hechos de la ventana, agrupados por historia, primarios garantizados,
    de más nuevo a más antiguo.

    Cada candidato: ``date``, ``title``, ``source``, ``kind`` y opcionales
    ``url``, ``materiality``, ``detail``, ``id``. Sin fecha no entra.
    """
    from app.services.news_story_cluster import exact_key

    cutoff = now - timedelta(days=window_days)
    tokens = _company_tokens(ticker, company_name)
    pool: list[dict[str, Any]] = []
    for cand in candidates:
        dt = _as_datetime(cand.get("date"))
        title = str(cand.get("title") or "").strip()
        if dt is None or not title or dt < cutoff or dt > now + timedelta(days=1):
            continue
        kind = cand.get("kind") or KIND_NEWS
        materiality = cand.get("materiality")
        if kind == KIND_NEWS and (materiality is None or materiality < min_materiality):
            continue
        pool.append({**cand, "kind": kind, "_dt": dt, "_sig": _story_signature(title, tokens), "_key": exact_key(title)})

    # Más antiguo primero: el primer aviso fija la fecha de la historia.
    pool.sort(key=lambda c: c["_dt"])
    rare = _rare_tokens(pool)
    groups: list[list[dict[str, Any]]] = []
    for cand in pool:
        for group in groups:
            # Los hechos de la SEC no se agrupan con prensa: un 8-K es su propio hecho.
            if cand["kind"] == KIND_SEC or group[0]["kind"] == KIND_SEC:
                continue
            # Solo contra la primera noticia del grupo: comparar con cualquier
            # miembro encadenaba historias distintas (medido con ASTS: un
            # grupo de 257 noticias desde el 5-oct).
            if _same_story(group[0], cand, rare):
                group.append(cand)
                break
        else:
            groups.append([cand])

    events: list[dict[str, Any]] = []
    for group in groups:
        primary = next((m for m in group if m["kind"] in _PRIMARY_KINDS), None)
        rep = primary or max(group, key=lambda m: (m.get("materiality") or 0, -m["_dt"].timestamp()))
        first = group[0]
        sources = []
        for member in group:
            if member.get("source") and member["source"] not in sources:
                sources.append(member["source"])
        events.append(
            {
                "date": first["_dt"].date().isoformat(),
                "title": rep.get("title"),
                "source": rep.get("source"),
                "kind": rep["kind"],
                "url": rep.get("url"),
                "detail": rep.get("detail"),
                "id": rep.get("id"),
                "materiality": max((m.get("materiality") or 0) for m in group) or None,
                "coverage": len(group),
                "other_sources": [s for s in sources if s != rep.get("source")][:4],
                "_dt": first["_dt"],
            }
        )

    newest_first = sorted(events, key=lambda e: e["_dt"], reverse=True)
    primaries = [e for e in newest_first if e["kind"] in _PRIMARY_KINDS][:max_primary]
    chosen = list(primaries)
    # El resto, por relevancia dentro de la ventana: primero lo de los
    # últimos ``FRESH_DAYS`` días; dentro, la historia que cuentan más medios
    # y luego la de más materialidad; a igualdad, la más nueva. Se muestra
    # después por fecha.
    fresh_cut = now - timedelta(days=FRESH_DAYS)
    ranked = sorted(
        (e for e in newest_first if e not in chosen),
        key=lambda e: (e["_dt"] < fresh_cut, -e["coverage"], -(e.get("materiality") or 0), -e["_dt"].timestamp()),
    )
    for event in ranked:
        if len(chosen) >= limit:
            break
        chosen.append(event)
    chosen.sort(key=lambda e: e["_dt"], reverse=True)
    for event in chosen:
        event.pop("_dt", None)
    return chosen[:limit]


def apply_recency_rule(events: list[dict[str, Any]], latest_periodic: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Marca cada hecho como posterior (o no) al último informe periódico."""
    cut = _as_datetime((latest_periodic or {}).get("date"))
    for event in events:
        when = _as_datetime(event.get("date"))
        event["after_latest_report"] = bool(cut and when and when.date() > cut.date())
    return events


def collect_recent_events(db, company, *, now: datetime | None = None, ir_status: dict | None = None) -> dict[str, Any]:
    """Lee de la base (sin red) los hechos recientes de ``company``.

    Las consultas pasan por el filtro de tenant de la sesión (como el resto de
    la evidencia de la tesis).
    """
    from sqlalchemy import desc, select

    from app.models.entities import Document, NewsEvent

    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=WINDOW_DAYS)
    candidates: list[dict[str, Any]] = []
    counts = {"sec": 0, "press": 0, "ir": 0, "news": 0}
    sec_urls: set[str] = set()

    # 1. Documentos SEC (8-K/6-K) e IR guardados por la ingesta de la tesis.
    latest_periodic: dict[str, Any] | None = None
    docs = db.scalars(
        select(Document)
        .where(
            Document.company_id == company.id,
            Document.source_type.in_(("SEC", "IR")),
        )
        .order_by(desc(Document.published_at))
        .limit(200)
    ).all()
    for doc in docs:
        meta = doc.metadata_ or {}
        form = str(meta.get("form") or "").upper() or _form_from_title(doc.title)
        when = doc.published_at or (meta.get("filing_date"))
        if doc.source_type == "SEC" and form in PERIODIC_FORMS and when is not None:
            dt = _as_datetime(when)
            if dt and (latest_periodic is None or dt > _as_datetime(latest_periodic["date"])):
                latest_periodic = {"form": form, "date": dt.date().isoformat(), "url": doc.source_url}
            continue
        if doc.source_type == "SEC" and form in CURRENT_REPORT_FORMS:
            url = doc.source_url or ""
            if url in sec_urls:
                continue
            sec_urls.add(url)
            detail = items_label(meta.get("items"))
            candidates.append(
                {
                    "date": when,
                    "title": f"{form} presentado ante la SEC" + (f": {detail}" if detail else ""),
                    "source": "SEC EDGAR",
                    "kind": KIND_SEC,
                    "url": doc.source_url,
                    "detail": detail,
                }
            )
        elif doc.source_type == "IR":
            # La página de inversores no siempre da fecha: sin fecha no entra.
            if doc.published_at is None:
                continue
            candidates.append(
                {"date": doc.published_at, "title": doc.title, "source": "Página de inversores", "kind": KIND_IR, "url": doc.source_url}
            )

    # 2. Pipeline de noticias (incluye 8-K que entran como noticia y comunicados).
    rows = db.scalars(
        select(NewsEvent)
        .where(NewsEvent.company_id == company.id, NewsEvent.date >= cutoff)
        .order_by(desc(NewsEvent.date))
        .limit(400)
    ).all()
    for row in rows:
        cand = news_candidate(row, sec_urls)
        if cand is not None:
            candidates.append(cand)

    events = select_recent_events(candidates, now=now, ticker=company.ticker, company_name=company.name)
    events = apply_recency_rule(events, latest_periodic)
    for event in events:
        key = {KIND_SEC: "sec", KIND_PRESS: "press", KIND_IR: "ir"}.get(event["kind"], "news")
        counts[key] += 1

    checked = [
        {
            "source": "SEC (8-K/6-K)",
            "found": counts["sec"],
            "note": None if counts["sec"] else f"ningún 8-K/6-K en los últimos {WINDOW_DAYS} días",
        },
        {
            "source": "Comunicados (Business Wire, PR Newswire, GlobeNewswire...)",
            "found": counts["press"],
            "note": None if counts["press"] else f"ningún comunicado en los últimos {WINDOW_DAYS} días",
        },
        {
            "source": "Página de inversores",
            "found": counts["ir"],
            "note": None if counts["ir"] else _ir_note(company, ir_status),
        },
        {
            "source": "Noticias (pipeline de la app)",
            "found": counts["news"],
            "note": None if counts["news"] else f"ninguna noticia material en los últimos {WINDOW_DAYS} días",
        },
    ]
    return {
        "status": "ok" if events else "pending",
        "source": "hechos recientes (SEC, comunicados, IR, noticias)",
        "window_days": WINDOW_DAYS,
        "as_of": now.date().isoformat(),
        "latest_periodic_report": latest_periodic,
        "items": events,
        "sources_checked": checked,
        **({} if events else {"detail": f"sin hechos fechados en los últimos {WINDOW_DAYS} días"}),
    }


# Anuncios de despachos que buscan demandantes (llegan por GlobeNewswire o PR
# Newswire con titulares en mayúsculas): ``is_law_firm_solicitation`` no
# cazaba «ROSEN ... Encourages ... Investors», «INVESTORS WITH LOSSES HAVE
# UNTIL» ni «DEADLINE: RGRD Law» (medido en prod, ASTS, oct-nov 2026).
_CLASS_ACTION_RE = re.compile(
    r"class\s+action|securities\s+fraud|lead\s+plaintiff|"
    r"\b(?:investors?|shareholders?|stockholders?)\b.{0,40}\b(?:alert|losses|lost|lawsuit|deadline|encourag\w*|reminded|contact)\b|"
    r"\b(?:alert|deadline|encourages|reminds)\b.{0,60}\b(?:investors?|shareholders?|stockholders?)\b|"
    r"\b(?:rosen|pomerantz|bragar|levi\s*&\s*korsinsky|glancy|faruqi|bronstein|gainey|kessler\s+topaz|"
    r"robbins\s+geller|rgrd|schall|portnoy|bernstein\s+liebhard|kahn\s+swick|rosen\s+law)\b",
    re.IGNORECASE,
)


# Páginas de cotización o de datos que el pipeline guarda como noticia y
# ``is_data_page_headline`` no reconoce (medido en prod, ASTS, nov-2026).
_DATA_PAGE_RE = re.compile(
    r"seasonal\s+returns?\s+chart|(?:rendimientos|rentabilidades)\s+estacionales|"
    r"hits?\s+(?:a\s+)?(?:new\s+)?52[- ]week\s+(?:low|high)\s+at|m[ií]nimos?\s+de\s+52\s+semanas\s+en|"
    r"m[aá]ximos?\s+de\s+52\s+semanas\s+en|lobbying\s+profile|"
    r"what'?s\s+going\s+on\s+with\s+.{0,60}\bstock\b",
    re.IGNORECASE,
)


def _is_class_action_ad(headline: str | None) -> bool:
    text = headline or ""
    return bool(_CLASS_ACTION_RE.search(text) or _DATA_PAGE_RE.search(text))


def news_candidate(row, sec_urls: set[str] | None = None) -> dict[str, Any] | None:
    """Candidato a hecho reciente desde una fila del pipeline de noticias, o
    None si no es un hecho de la empresa (captación de despachos, páginas de
    cotización, participaciones 13G/13D, formularios 3/4/144, informes
    periódicos que ya van en su propia sección)."""
    from app.services.ticker_news_lane import is_data_page_headline, is_law_firm_solicitation

    sec_urls = sec_urls if sec_urls is not None else set()
    meta = row.metadata_ or {}
    headline = meta.get("source_headline") or row.title
    if is_law_firm_solicitation(headline, None) or is_data_page_headline(headline) or _is_class_action_ad(headline):
        return None
    kind = news_kind(row.source, row.url, meta)
    detail = None
    if kind == KIND_SEC:
        if row.url and row.url in sec_urls:
            return None
        form = str(meta.get("form") or "").upper() or _form_from_title(row.title)
        if form not in CURRENT_REPORT_FORMS:
            return None
        if row.url:
            sec_urls.add(row.url)
        detail = items_label(meta.get("items"))
    return {
        "id": row.id,
        "date": row.date,
        "title": headline,
        "source": row.source,
        "kind": kind,
        "url": row.url,
        "materiality": row.materiality_score,
        "detail": detail,
    }


def pick_recent_news_rows(rows: list, *, now: datetime, ticker: str | None, company_name: str | None, limit: int) -> list:
    """Filas del pipeline de noticias para la tesis, por fecha y no por
    «materialidad»: las de la ventana, agrupadas por historia, comunicados y
    8-K con hueco garantizado, de más nueva a más antigua."""
    by_id = {row.id: row for row in rows}
    candidates = [c for c in (news_candidate(row) for row in rows) if c is not None]
    events = select_recent_events(
        candidates, now=now, ticker=ticker, company_name=company_name, limit=limit, max_primary=min(MAX_PRIMARY, max(1, limit // 2))
    )
    return [by_id[e["id"]] for e in events if e.get("id") in by_id]


def _ir_note(company, ir_status: dict | None) -> str:
    if ir_status and ir_status.get("status") != "ok" and ir_status.get("detail"):
        return str(ir_status["detail"]).rstrip(".")
    if not (getattr(company, "ir_url", None) or "").strip():
        return "la ficha de la empresa no tiene URL de la página de inversores"
    return "sin comunicados fechados de la página de inversores"


def _form_from_title(title: str | None) -> str:
    match = re.search(r"\b(10-K/A|10-K|10-Q/A|10-Q|20-F|40-F|8-K/A|8-K|6-K)\b", title or "")
    return match.group(1) if match else ""


def _md_escape(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def recent_events_markdown(block: dict[str, Any] | None) -> str:
    """Sección «Hechos recientes» de la tesis: fecha · tipo · fuente · titular."""
    block = block or {}
    window = block.get("window_days") or WINDOW_DAYS
    latest = block.get("latest_periodic_report")
    lines = [f"### Hechos recientes (últimos {window} días, de más nuevo a más antiguo)"]
    if latest:
        lines.append(
            f"Último informe periódico: {latest.get('form')} del {latest.get('date')}. "
            "Lo marcado como posterior prevalece sobre lo que dice ese informe; "
            "nada anterior sustituye a un hecho más reciente."
        )
    else:
        lines.append("Último informe periódico: no localizado en la base; los hechos van solo por fecha.")
    items = block.get("items") or []
    if not items:
        lines.append(f"- Pendiente: {block.get('detail') or 'sin hechos fechados en la ventana'}.")
    for item in items:
        tag = item.get("kind") or KIND_NEWS
        extra = ""
        if item.get("coverage", 1) > 1:
            extra = f" (también en {', '.join(item.get('other_sources') or [])})" if item.get("other_sources") else ""
        after = " · posterior al último informe" if item.get("after_latest_report") else ""
        url = f" — {item['url']}" if item.get("url") else ""
        lines.append(
            f"- {item.get('date')} · {tag} · {_md_escape(str(item.get('source') or '?'))}: "
            f"{_md_escape(str(item.get('title') or ''))}{extra}{after}{url}"
        )
    checked = block.get("sources_checked") or []
    if checked:
        parts = []
        for entry in checked:
            if entry.get("found"):
                parts.append(f"{entry['source']}: {entry['found']}")
            else:
                parts.append(f"{entry['source']}: 0 ({entry.get('note') or 'nada encontrado'})")
        lines.append("Fuentes consultadas: " + "; ".join(parts) + ".")
    return "\n".join(lines)
