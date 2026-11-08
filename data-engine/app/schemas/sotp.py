"""Cuerpo del PUT /valuation/{ticker}/sotp (desglose por partes editable).

Tipos laxos a propósito: la validación con mensajes en español la hace
``app.valuation.sotp.normalize_user_sotp`` (rangos, campos que faltan por
parte). Aquí solo se declaran los campos para el contrato OpenAPI.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class SotpModelIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    currency: str | None = None
    base_year: Any = None
    valuation_year: Any = None
    discount_years: Any = None
    discount_rate: Any = None
    shares_current: Any = None
    dilution: list[dict[str, Any]] | None = None
    parts: list[dict[str, Any]] | None = None
    scenarios: list[dict[str, Any]] | None = None
    author: str | None = None
    source: str | None = None
    stated_value_per_share: Any = None
