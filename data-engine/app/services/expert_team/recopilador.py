"""«Recopilador»: el experto que hace el inventario de impulsores de valor.

Feature aprobada por Nico (4-nov-2026): «al pedir la tesis, Cerebro y su equipo
de expertos deben llegar a todas esas conclusiones», «añade agentes expertos si
hace falta, por ejemplo agente recopilador de todo». Es la etapa (a) del
pipeline automático de la tesis (SPEC_ADDENDUM «inventario de impulsores»):
lista todo lo que mueve el valor de la empresa — negocios, contratos, mercados,
gobierno, activos, opciones, restricciones, pasivos y catalizadores — con su
fuente, ANTES de buscar inputs y valorar. Los roles siguientes (valorador,
mezcla de analistas, escéptico) leen este inventario y le ponen tratamiento.

Cómo trabaja (nada por ticker):

1. Recoge evidencia con las herramientas de lectura del equipo
   (``financial_facts``, ``news_events``, ``risk_events``) más los pasajes de
   los documentos ingeridos de la empresa (filings, notas de prensa, notas de
   socios) que hablan de contratos, segmentos, licencias, cartera, etc.
   Sin scrapers externos: solo lo que ya está en la base del tenant.
2. Un LLM devuelve el inventario en JSON (``RECOPILADOR_CONTRACT``).
3. Fail-closed: si el JSON no es válido, si un impulsor no cumple el esquema de
   :mod:`app.services.value_driver_service`, si no cita evidencia de esta
   corrida, si su URL no es la de la evidencia citada o si la cita literal no
   aparece en ella, no se guarda NADA (un reintento con los problemas).
4. Un post de X u otra red social es ``redes`` y un foro es ``foro``: el
   servicio los deja como rumor aunque el modelo diga «firmado».
5. Se guarda con ``ValueDriverService.upsert_many`` (idempotente, histórico).

Solo corre con ``EXPERT_TEAM_ENABLED``; apagado no hace nada ni llama al LLM.
No toca la tesis: el gancho en thesis_service queda como lead (lane c2acb5b0).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.json import parse_json_response
from app.models.entities import Company, Document, DocumentChunk
from app.services.expert_team.experts import ExpertSpec, Reasoner, gather_evidence
from app.services.expert_team.ledger import EvidenceLedger
from app.services.expert_team.models import RunContext, ToolOutput, ToolSpec
from app.services.value_driver_service import (
    ValueDriverError,
    ValueDriverItem,
    ValueDriverService,
    normalize_item,
)

logger = logging.getLogger(__name__)

RECOPILADOR_NAME = "recopilador"
RECOPILADOR_TOOLS: tuple[str, ...] = ("company_documents", "news_events", "financial_facts", "risk_events")
MAX_ATTEMPTS = 2
MAX_DRIVERS = 80
#: Pasajes de documentos: cuántos documentos recientes y cuántos pasajes por documento.
DOC_MAX_DOCUMENTS = 12
DOC_MAX_PASSAGES_PER_DOC = 4
DOC_PASSAGE_CHARS = 1500
#: Palabras que señalan un impulsor de valor en un pasaje (genéricas, es/en).
DRIVER_SIGNAL_WORDS: tuple[str, ...] = (
    "agreement",
    "contract",
    "backlog",
    "segment",
    "license",
    "licence",
    "spectrum",
    "patent",
    "partner",
    "memorandum",
    "letter of intent",
    "commitment",
    "prepay",
    "joint venture",
    "award",
    "subsidiar",
    "convertible",
    "litigation",
    "capacity",
    "launch",
    "approval",
    "regulator",
    "acuerdo",
    "contrato",
    "cartera",
    "segmento",
    "licencia",
    "espectro",
    "patente",
    "socio",
    "compromiso",
    "adjudica",
    "convertible",
    "litigio",
    "capacidad",
    "lanzamiento",
    "aprobaci",
)
#: Dominios de redes sociales y foros: lo que dicen es rumor hasta que lo confirme un documento.
SOCIAL_HOSTS: tuple[str, ...] = (
    "x.com",
    "twitter.com",
    "facebook.com",
    "instagram.com",
    "threads.net",
    "tiktok.com",
    "linkedin.com",
    "youtube.com",
    "t.me",
    "bsky.app",
    "truthsocial.com",
)
FORUM_HOSTS: tuple[str, ...] = ("reddit.com", "stocktwits.com", "seekingalpha.com/instablog", "discord.com")

RECOPILADOR_CONTRACT = (
    'Responde SOLO con JSON: {"drivers": [{"driver_key": str (minúsculas y _), "category": '
    '"linea_negocio|contrato|geografia|gobierno|activo|opcion|restriccion|pasivo|catalizador", '
    '"name": str, "status": "firmado|anunciado_oficial|loi_mou|regulatorio_pendiente|rumor", '
    '"economics": {"amount": numero|null, "currency": str|null, "amount_usd": numero|null, '
    '"term": str|null, "unit_economics": str|null}, "timing": str|null, '
    '"source_type": "filing|nota_empresa|nota_socio|regulador|prensa|analista|foro|redes", '
    '"evidence": "oficial|estimado|rumor", "citations": ["ev-N"], "source_url": str, '
    '"source_quote": str (literal, copiada de la evidencia citada), "as_of": "AAAA-MM-DD"|null, '
    '"headline": bool, "treatment": "pendiente"}]}. Cada impulsor cita la evidencia de la que '
    "sale; la URL es la de esa evidencia y la cita está copiada de ella, palabra por palabra. Sin "
    "evidencia no hay impulsor. Un post en redes o un foro es rumor."
)


@dataclass
class RecopiladorResult:
    """Qué hizo el Recopilador en una corrida."""

    status: str  # disabled | no_company | no_data | stored | rejected | error
    stored: int = 0
    unchanged: int = 0
    drivers: list[ValueDriverItem] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    llm_calls: int = 0
    prompt_version: str | None = None
    tool_errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "stored": self.stored,
            "unchanged": self.unchanged,
            "drivers": [d.driver_key for d in self.drivers],
            "problems": list(self.problems),
            "llm_calls": self.llm_calls,
            "prompt_version": self.prompt_version,
            "tool_errors": list(self.tool_errors),
        }


def _fold(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _host_path(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return f"{host}{parsed.path or ''}"


def _matches(host_path: str, domains: tuple[str, ...]) -> bool:
    host = host_path.split("/", 1)[0]
    for domain in domains:
        if "/" in domain:
            if host_path.startswith(domain):
                return True
        elif host == domain or host.endswith("." + domain):
            return True
    return False


def social_source_type(url: str | None) -> str | None:
    """``redes`` o ``foro`` si la URL es de una red social o un foro; si no, None."""
    if not url:
        return None
    host_path = _host_path(url)
    if _matches(host_path, FORUM_HOSTS):
        return "foro"
    if _matches(host_path, SOCIAL_HOSTS):
        return "redes"
    return None


def company_documents_tool(db: Session) -> ToolSpec:
    """Pasajes de los documentos ingeridos de la empresa que hablan de impulsores."""

    def company_documents(ctx: RunContext) -> list[ToolOutput]:
        if not ctx.ticker:
            return []
        company = db.scalars(select(Company).where(Company.ticker == ctx.ticker)).first()
        if company is None:
            return []
        docs = db.scalars(
            select(Document)
            .where(
                Document.tenant_id == ctx.tenant_id,
                Document.company_id == company.id,
                Document.retention_tombstoned_at.is_(None),
            )
            .order_by(Document.published_at.desc().nullslast(), Document.id.desc())
            .limit(DOC_MAX_DOCUMENTS)
        ).all()
        # Lote único de chunks para todos los documentos (anti N+1): una
        # consulta con IN + agrupación en memoria conserva el orden por
        # documento y chunk_index del bucle anterior (1 query por documento).
        chunks_by_doc: dict[int, list[DocumentChunk]] = {}
        if docs:
            doc_ids = [doc.id for doc in docs]
            for chunk in db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.tenant_id == ctx.tenant_id, DocumentChunk.document_id.in_(doc_ids))
                .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
            ).all():
                chunks_by_doc.setdefault(chunk.document_id, []).append(chunk)
        out: list[ToolOutput] = []
        for doc in docs:
            chunks = chunks_by_doc.get(doc.id, [])
            hits = [c for c in chunks if any(w in _fold(c.text) for w in DRIVER_SIGNAL_WORDS)]
            for chunk in hits[:DOC_MAX_PASSAGES_PER_DOC]:
                out.append(
                    ToolOutput(
                        source={
                            "table": "document_chunks",
                            "document_id": str(doc.id),
                            "title": doc.title or "",
                            "source_type": doc.source_type or "",
                            "url": doc.source_url or "",
                            "date": doc.published_at.date().isoformat() if doc.published_at else "",
                        },
                        data={"text": (chunk.text or "")[:DOC_PASSAGE_CHARS]},
                    )
                )
        return out

    return ToolSpec(
        name="company_documents",
        fn=company_documents,
        description="Pasajes de filings y notas ingeridos que hablan de contratos, segmentos, activos…",
    )


def build_recopilador_tools(db: Session) -> dict[str, ToolSpec]:
    from app.services.expert_team.tools import build_tools

    tools = {k: v for k, v in build_tools(db).items() if k in RECOPILADOR_TOOLS}
    tools["company_documents"] = company_documents_tool(db)
    return tools


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def parse_inventory(
    parsed: Any, ledger: EvidenceLedger, *, expert: str = RECOPILADOR_NAME, partial: bool = False
) -> tuple[list[ValueDriverItem], list[str]]:
    """JSON del modelo → impulsores validados, o la lista de problemas.

    Fail-closed: un solo problema invalida el inventario entero. Con ``partial`` (último recurso, tras los
    reintentos) devuelve los impulsores que pasan TODAS las comprobaciones y los problemas de los demás:
    un impulsor mal citado ya no tira los bien citados.
    """
    problems: list[str] = []
    if not isinstance(parsed, dict) or not isinstance(parsed.get("drivers"), list):
        return [], ["el JSON no trae la lista «drivers»"]
    raw_drivers = parsed["drivers"]
    if len(raw_drivers) > MAX_DRIVERS:
        return [], [f"más de {MAX_DRIVERS} impulsores"]
    service = ValueDriverService()
    items: list[ValueDriverItem] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_drivers):
        label = f"#{index + 1}"
        if not isinstance(raw, dict):
            problems.append(f"{label}: no es un objeto")
            continue
        label = str(raw.get("driver_key") or label)
        citations = [c for c in raw.get("citations") or () if isinstance(c, str)]
        cited = [ledger.get(c) for c in citations]
        cited = [e for e in cited if e is not None and e.expert == expert]
        if not citations or len(cited) != len(citations):
            problems.append(f"{label}: no cita evidencia de esta corrida")
            continue
        url = str(raw.get("source_url") or "").strip()
        urls = {str(e.source.get("url") or "").strip() for e in cited} - {""}
        if not url or url not in urls:
            problems.append(f"{label}: la URL no es la de la evidencia citada")
        quote = _fold(raw.get("source_quote"))
        corpus = " ".join(_fold(json.dumps(e.data, ensure_ascii=False, default=str)) for e in cited)
        corpus = corpus + " " + " ".join(_fold(e.data.get("text")) for e in cited if isinstance(e.data, dict))
        if not quote or quote not in corpus:
            problems.append(f"{label}: la cita no aparece literal en la evidencia citada")
        source_type = str(raw.get("source_type") or "")
        social = social_source_type(url)
        if social is not None:
            source_type = social
        raw_economics = raw.get("economics")
        economics: dict[str, Any] = raw_economics if isinstance(raw_economics, dict) else {}
        document_ids = [
            int(e.source["document_id"]) for e in cited if str(e.source.get("document_id", "")).isdigit()
        ]
        item = ValueDriverItem(
            driver_key=str(raw.get("driver_key") or ""),
            category=str(raw.get("category") or ""),
            name=str(raw.get("name") or ""),
            status=str(raw.get("status") or ""),
            source_type=source_type,
            evidence=str(raw.get("evidence") or ""),
            source_url=url or None,
            source_quote=str(raw.get("source_quote") or "").strip() or None,
            document_id=document_ids[0] if document_ids else None,
            as_of=_as_date(raw.get("as_of")),
            economics={k: v for k, v in economics.items() if v is not None},
            timing=str(raw["timing"]) if isinstance(raw.get("timing"), str) else None,
            headline=raw.get("headline") is True,
            treatment="pendiente",
            metadata={"citations": citations, "expert": expert},
        )
        item = normalize_item(item)
        problems.extend(f"{label}: {p}" for p in service.validate(item))
        if item.driver_key in seen:
            problems.append(f"{label}: clave repetida")
        seen.add(item.driver_key)
        if partial and any(p.startswith(f"{label}: ") for p in problems):
            continue
        items.append(item)
    if partial:
        return items, problems
    if problems:
        return [], problems
    return items, []


async def run_recopilador(
    db: Session,
    *,
    ctx: RunContext,
    reasoner: Reasoner,
    spec: ExpertSpec | None = None,
    tools: Mapping[str, ToolSpec] | None = None,
    enabled: bool | None = None,
) -> RecopiladorResult:
    """Corre el Recopilador para ``ctx.ticker`` y guarda el inventario del tenant.

    ``enabled`` None = ``EXPERT_TEAM_ENABLED``. Apagado: no llama al LLM ni escribe.
    """
    from app.core.config import get_settings
    from app.services.expert_team.roster import recopilador_expert
    from app.services.prompt_registry import get_prompt

    if enabled is None:
        enabled = bool(get_settings().expert_team_enabled)
    if not enabled:
        return RecopiladorResult(status="disabled")
    if type(ctx.tenant_id) is not int or not ctx.ticker:
        return RecopiladorResult(status="no_company", problems=["hace falta tenant y empresa"])
    company = db.scalars(select(Company).where(Company.ticker == ctx.ticker)).first()
    if company is None:
        return RecopiladorResult(status="no_company")
    spec = spec or recopilador_expert()
    tools = tools if tools is not None else build_recopilador_tools(db)
    ledger = EvidenceLedger()
    evidence, tool_errors = await gather_evidence(spec, ctx, tools, ledger)
    prompt = get_prompt(spec.prompt_name, lang="es")
    result = RecopiladorResult(status="no_data", prompt_version=prompt.version, tool_errors=tool_errors)
    if not evidence:
        return result
    system = f"{prompt.text}\n\n{RECOPILADOR_CONTRACT}"
    items: list[ValueDriverItem] = []
    payload: dict[str, Any] = {"ticker": ctx.ticker, "company": company.name, "evidence": evidence}
    for _ in range(MAX_ATTEMPTS):
        result.llm_calls += 1
        try:
            text = await reasoner(
                system,
                json.dumps(payload, ensure_ascii=False, default=str),
                spec.max_tokens,
                f"expert_team.{spec.name}",
            )
        except Exception as exc:  # sin LLM o sin presupuesto: no se escribe nada
            result.status = "error"
            result.problems = [f"llm:{type(exc).__name__}"]
            return result
        try:
            parsed = parse_json_response(text)
        except Exception:
            parsed = None
        items, problems = parse_inventory(parsed, ledger, expert=spec.name)
        if not problems:
            result.problems = []
            break
        result.problems = problems
        payload["problems_previous_answer"] = problems[:20]
    else:
        # Que no se pierda nada de lo bien citado: se guardan los impulsores que pasan todas las
        # comprobaciones; los demás quedan descartados con su motivo en ``problems``.
        items, problems = parse_inventory(parsed, ledger, expert=spec.name, partial=True)
        if not items:
            result.status = "rejected"
            return result
        result.problems = problems
        logger.info("recopilador %s: %d impulsores guardados, descartados: %s", ctx.ticker, len(items),
                    "; ".join(problems[:10]))
    try:
        outcomes = ValueDriverService().upsert_many(db, company=company, tenant_id=ctx.tenant_id, items=items)
    except ValueDriverError as exc:
        result.status = "rejected"
        result.problems = exc.problems
        return result
    result.status = "stored"
    result.drivers = items
    result.stored = sum(1 for o in outcomes if o.changed)
    result.unchanged = sum(1 for o in outcomes if not o.changed)
    return result


__all__ = [
    "DRIVER_SIGNAL_WORDS",
    "FORUM_HOSTS",
    "RECOPILADOR_CONTRACT",
    "RECOPILADOR_NAME",
    "RECOPILADOR_TOOLS",
    "SOCIAL_HOSTS",
    "RecopiladorResult",
    "build_recopilador_tools",
    "company_documents_tool",
    "parse_inventory",
    "run_recopilador",
    "social_source_type",
]
