"""Contrato público unificado de ProPicks (propicks-unified-v1).

Solo forma y invariantes de datos: no calcula ninguna cifra. Los campos
públicos van en camelCase (contrato acordado con el frontend). Históricos y
simulaciones quedan fuera (extra="forbid").
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

SCHEMA_VERSION = "propicks-unified-v1"

DataStatus = Literal["ok", "missing", "stale", "disputed", "unverified", "invalid", "not_applicable"]
BlockStatus = Literal["ok", "empty", "partial", "error"]
ErrorKind = Literal[
    "timeout", "unauthenticated", "forbidden", "rate_limited", "unavailable", "invalid_response"
]
EligibilityState = Literal["investigate", "quality_waiting_price", "review_data", "excluded"]

_NULL_STATUSES = {"missing", "invalid", "not_applicable"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Datum(_Strict):
    value: float | int | str | bool | None = None
    status: DataStatus
    unit: str | None = None
    asOf: str | None = None
    sourceAsOf: str | None = None
    formulaVersion: str | None = None
    reasonCodes: list[str] = []

    @model_validator(mode="after")
    def _invariants(self) -> Datum:
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("value must be finite")
        if self.status in _NULL_STATUSES and self.value is not None:
            raise ValueError(f"value must be null when status is {self.status}")
        if self.status == "ok" and self.value is None:
            raise ValueError("status ok requires a value")
        return self


class Listing(_Strict):
    ticker: str
    name: str | None = None
    exchange: str | None = None
    currency: str | None = None
    validFrom: str | None = None
    validTo: str | None = None
    status: Literal["active", "delisted", "unknown"] = "unknown"
    identityStatus: DataStatus = "unverified"
    identityEvidence: list[str] = []
    identityReasonCodes: list[str] = []
    listingId: str | None = None
    # Hechos distintos (no mezclar): negociación, instrumento y emisor.
    tradingStatus: Literal["trading", "suspended", "unknown"] = "unknown"
    instrumentStatus: Literal["active", "cancelled", "unknown"] = "unknown"
    issuerLegalStatus: Literal["active", "liquidating", "dissolved", "unknown"] = "unknown"


class Coverage(_Strict):
    present: int
    required: int
    total: int


class Quality(_Strict):
    passed: bool | None = None
    score: Datum
    # Overlay quality-v1 por fila (``passed``); el score tiene su propia política.
    policyVersion: str | None = None
    scorePolicyVersion: str | None = None
    coverage: Coverage
    reasonCodes: list[str] = []

    @model_validator(mode="after")
    def _score_range(self) -> Quality:
        v = self.score.value
        if v is not None:
            if isinstance(v, bool) or not isinstance(v, int | float) or not 0 <= v <= 100:
                raise ValueError("quality score must be 0..100")
            if not self.scorePolicyVersion:
                raise ValueError("quality score requires scorePolicyVersion")
        return self


class Valuation(_Strict):
    status: DataStatus
    price: Datum
    fcfYield: Datum
    priceToBook: Datum
    marginOfSafety: Datum


class Dca(_Strict):
    status: DataStatus
    level: Datum
    periodState: Literal["confirmed", "forming"] | None = None
    confirmedLevel: Datum
    priceVerified: bool | None = None
    scanAsOf: str | None = None
    formulaVersion: str | None = None


class Tracking(_Strict):
    held: bool | None = None
    watched: bool | None = None


class Eligibility(_Strict):
    state: EligibilityState
    reasonCodes: list[str] = []


class UnifiedPick(_Strict):
    instrumentId: str
    issuerId: str | None = None
    listing: Listing
    quality: Quality
    valuation: Valuation
    dca: Dca
    evidenceFlags: list[str] = []
    reviewReasons: list[str] = []
    tracking: Tracking
    eligibility: Eligibility
    runId: int | None = None
    asOf: str

    @model_validator(mode="after")
    def _delisted_excluded(self) -> UnifiedPick:
        if self.listing.status == "delisted" and self.eligibility.state != "excluded":
            raise ValueError("delisted listing must be excluded")
        return self


class ResultCoverage(_Strict):
    universe: int | None = None
    evaluated: int | None = None
    qualityPassed: int | None = None
    rankable: int | None = None
    pendingReview: int | None = None
    # Con identidad verificada por el resolver, sobre ``evaluated``.
    identityVerified: int | None = None


class BlockError(_Strict):
    kind: ErrorKind
    retryAfterSeconds: int | None = None
    reference: str | None = None


class Block(_Strict):
    status: BlockStatus
    asOf: str | None = None
    error: BlockError | None = None


class UnifiedResult(_Strict):
    schemaVersion: Literal["propicks-unified-v1"]
    status: BlockStatus
    asOf: str
    runId: int | None = None
    coverage: ResultCoverage
    blocks: dict[Literal["quality", "valuation", "dca", "tracking"], Block]
    items: list[UnifiedPick]
