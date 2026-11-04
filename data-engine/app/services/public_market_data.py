"""Read-only public-data boundary. No promotion, provider calls or tenant bypass."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.public_market_data import PublicFinancialFact, PublicSourceDocument


@dataclass(frozen=True)
class PublicFact:
    fact_ref: str
    metric: str
    value: Decimal
    unit: str
    period_end: date
    filed: date | None
    as_of: date
    source_url: str
    source_checksum: str
    accession: str | None
    official: bool
    derived: bool
    concept: str


class PublicMarketDataRepository:
    """Explicit public namespace; never queries financial_facts or documents.

    Private overrides are deliberately NOT combined here: a later resolver must
    use the authenticated tenant reader, preserving namespaced references and
    the existing source/coherence policy. Flag OFF means no SQL at all.
    """

    def facts(self, db: Session, *, company_id: int, listing_key: str,
              unit: str, as_of: date) -> list[PublicFact]:
        if not get_settings().public_market_data_enabled:
            return []
        query = (select(PublicFinancialFact, PublicSourceDocument)
                 .join(PublicSourceDocument, PublicFinancialFact.source_document_id == PublicSourceDocument.id)
                 .where(PublicSourceDocument.company_id == company_id,
                        PublicSourceDocument.listing_key == listing_key,
                        PublicFinancialFact.unit == unit,
                        PublicFinancialFact.period_end <= as_of,
                        PublicFinancialFact.filed.is_not(None),
                        PublicFinancialFact.filed <= as_of)
                 .order_by(PublicFinancialFact.id))
        return [PublicFact(
            fact_ref=f"public:{fact.id}", metric=fact.metric, value=fact.value,
            unit=fact.unit, period_end=fact.period_end, filed=fact.filed, as_of=as_of,
            source_url=source.source_url, source_checksum=source.checksum,
            accession=fact.accession, official=source.official, derived=fact.derived,
            concept=":".join(x for x in (fact.concept_namespace, fact.concept_name) if x),
        ) for fact, source in db.execute(query)]
