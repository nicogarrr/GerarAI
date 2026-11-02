import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Company, MemoryItem

TOKEN_RE = re.compile(r"[a-zA-Z0-9_]{3,}")
# Memory is written from chat ONLY when the message itself starts with an explicit
# "recuerda ..." / "remember ..." instruction. No other word is a trigger.
MIN_NOTE_CHARS = 5
MAX_NOTE_CHARS = 600


def remember_note(question: str) -> str | None:
    """Texto a guardar si el mensaje es una orden explicita de recordar; si no, None.

    Sin regex con espacios repetidos (evita ReDoS): se recorre el texto por pasos.
    """
    text = (question or "").strip()
    lowered = text.lower()
    if lowered.startswith("por favor"):
        text = text[len("por favor"):].lstrip(" ,\t\r\n")
        lowered = text.lower()
    keyword = next((k for k in ("recuerda", "remember") if lowered.startswith(k)), None)
    if keyword is None:
        return None
    rest = text[len(keyword):]
    if rest and rest[0].isalnum():  # "recuerdas", "remembered"
        return None
    rest = rest.lstrip(" :,-\t\r\n")
    first = rest.split(None, 1)
    if first and first[0].lower() in ("que", "that"):
        rest = first[1] if len(first) > 1 else ""
    note = " ".join(rest.split())
    if len(note) < MIN_NOTE_CHARS or note.endswith("?"):
        return None
    return note[:MAX_NOTE_CHARS]


@dataclass(frozen=True)
class RetrievedMemory:
    item: MemoryItem
    score: float
    reason: str


def _tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(text)}


class MemoryService:
    """Lightweight external memory layer inspired by Mem0's retrieve/consolidate/write flow."""

    def retrieve(
        self,
        db: Session,
        query: str,
        company: Company | None = None,
        scope: str = "portfolio",
        limit: int = 6,
    ) -> list[RetrievedMemory]:
        query_tokens = _tokens(query)
        statement = select(MemoryItem).where(MemoryItem.status == "active")
        if company:
            # Las de cartera son las que no son de ninguna empresa: una nota de
            # ACME guardada antes con ámbito «portfolio» no entra en el chat de BETA.
            statement = statement.where(
                (MemoryItem.company_id == company.id)
                | ((MemoryItem.scope == "portfolio") & MemoryItem.company_id.is_(None))
            )
        else:
            statement = statement.where(MemoryItem.scope == scope)

        items = db.scalars(statement.order_by(desc(MemoryItem.updated_at)).limit(200)).all()
        ranked: list[RetrievedMemory] = []
        now = datetime.now(UTC)
        for item in items:
            content_tokens = _tokens(item.content)
            overlap = len(query_tokens & content_tokens)
            updated_at = item.updated_at
            if updated_at and updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=UTC)
            age_days = max((now - updated_at).days if updated_at else 0, 0)
            recency = max(0.0, 1.0 - min(age_days, 365) / 365)
            company_boost = 2.0 if company and item.company_id == company.id else 0.5
            score = overlap * 2.5 + item.importance * 0.8 + recency + company_boost
            if overlap or item.importance >= 8 or (company and item.company_id == company.id):
                ranked.append(
                    RetrievedMemory(
                        item=item,
                        score=round(score, 3),
                        reason=f"overlap={overlap}; importance={item.importance}; recency={recency:.2f}",
                    )
                )

        return sorted(ranked, key=lambda memory: memory.score, reverse=True)[:limit]

    def write_explicit_note(
        self,
        db: Session,
        note: str,
        company: Company | None = None,
        scope: str = "portfolio",
    ) -> MemoryItem:
        """Guarda una nota pedida con "recuerda ...". Solo MemoryItem (con tenant de la sesion):
        nunca toca cartera, posiciones ni importaciones."""
        item = MemoryItem(
            company_id=company.id if company else None,
            scope="company" if company else scope,
            memory_type="chat_memory",
            importance=7,
            content=note,
            source_type="chat",
            metadata_={"write_policy": "explicit_remember_instruction"},
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item
