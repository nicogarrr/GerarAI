"""Claim scoping: which claims belong to the thesis being read.

Claims are created per ``ThesisVersion`` (``_persist_claims`` writes a fresh
Claim row for every generation), but five consumers read them by
``company_id`` alone: the thesis dependency graph, the red team, the moat
assessment, the company chat, and claim matching.

The consequences were concrete:

* every regeneration added ~5 orphaned claims from the previous version, and
  ``red_team_score`` fell monotonically with each one. A claim with
  ``materiality_score >= 7`` and no evidence costs 8 points, so three
  regenerations drove a healthy company to 0/100. The score was a function of
  how many times the thesis had been regenerated, not of the risk.
* the graph put a node per stale claim into the CURRENT version;
* the chat cited claims that no longer belonged to the thesis it was answering
  about;
* ``match_claims`` returned superseded claims and ``apply_suggestion`` then
  mutated their status in place, so a document could "contradict" a claim from
  a thesis that had been superseded months earlier.

This module centralises the rule so the five call sites cannot drift apart
again.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Claim, Company, ThesisVersion


def latest_thesis_version(db: Session, company: Company | int) -> ThesisVersion | None:
    """Highest version in the session tenant, including drafts as before.

    Accept a global company or its ID so all existing consumers use one rule.
    Publication eligibility remains a separate gate, not a selection filter.
    """
    company_id = company.id if isinstance(company, Company) else company
    return db.scalar(
        select(ThesisVersion)
        .where(ThesisVersion.company_id == company_id)
        .order_by(ThesisVersion.version.desc())
        .limit(1)
    )


def claims_for_thesis(
    db: Session,
    company: Company,
    thesis_version_id: int | None,
    *,
    order_by_materiality: bool = True,
    limit: int | None = None,
) -> list[Claim]:
    """Claims of ONE thesis version.

    ``thesis_version_id=None`` means "the claims that belong to no thesis yet",
    which is the set an evidence scan may legitimately attach to. It never
    means "every claim of the company", because that is the bug.
    """
    statement = select(Claim).options(selectinload(Claim.evidence))
    if thesis_version_id is None:
        statement = statement.where(
            Claim.company_id == company.id, Claim.thesis_version_id.is_(None)
        )
    else:
        statement = statement.where(
            Claim.company_id == company.id,
            Claim.thesis_version_id == thesis_version_id,
        )
    if order_by_materiality:
        statement = statement.order_by(Claim.materiality_score.desc(), Claim.updated_at.desc())
    else:
        statement = statement.order_by(Claim.updated_at.desc())
    if limit is not None:
        statement = statement.limit(limit)
    return list(db.scalars(statement).all())


def live_claims(
    db: Session,
    company: Company,
    *,
    thesis: ThesisVersion | None = None,
    limit: int | None = None,
) -> list[Claim]:
    """The claims a reader should see for this company right now.

    That is the claims of the current thesis version plus the company-level
    claims not yet attached to any thesis. Superseded versions are excluded.
    """
    version_id = thesis.id if thesis is not None else None
    if thesis is None:
        found = latest_thesis_version(db, company)
        version_id = found.id if found is not None else None

    statement = (
        select(Claim)
        .options(selectinload(Claim.evidence))
        .where(Claim.company_id == company.id)
        .where(
            or_(
                Claim.thesis_version_id.is_(None),
                Claim.thesis_version_id == version_id
                if version_id is not None
                else Claim.thesis_version_id.is_(None),
            )
        )
        .order_by(Claim.materiality_score.desc(), Claim.updated_at.desc())
    )
    if limit is not None:
        statement = statement.limit(limit)
    return list(db.scalars(statement).all())


def supersede_claims_of(db: Session, company_id: int, thesis_version_id: int) -> int:
    """Retire the claims of a thesis version that a new version replaces.

    Returns the number of rows closed. Without this the previous version's
    claims stay indistinguishable from the current ones.
    """
    from sqlalchemy import update

    result = db.execute(
        update(Claim)
        .where(
            Claim.company_id == company_id,
            Claim.thesis_version_id == thesis_version_id,
            Claim.status != "superseded",
        )
        .values(status="superseded")
    )
    return int(result.rowcount or 0)
