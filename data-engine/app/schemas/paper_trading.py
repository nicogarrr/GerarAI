from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.valuation.currency import canonical_currency_code, is_currency_code


class PaperProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    proposal_key: str = Field(min_length=1, max_length=120)
    ticker: str = Field(pattern=r"^[A-Za-z0-9.^=-]{1,20}$")
    direction: Literal["long", "short"]
    horizon: Literal["short", "five_years"]
    thesis: str = Field(min_length=20, max_length=20000)
    conviction: Decimal = Field(ge=0, le=1, allow_inf_nan=False)
    proposed_entry: Decimal = Field(gt=0, allow_inf_nan=False)
    stop: Decimal = Field(gt=0, allow_inf_nan=False)
    target: Decimal = Field(gt=0, allow_inf_nan=False)
    quantity: Decimal = Field(gt=0, le=1000000, allow_inf_nan=False)
    inference_basis: str = Field(min_length=10, max_length=10000)
    # Moneda del ancla de los niveles. Si viene, solo se acepta un quote en esa moneda.
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{1,8}$")

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, value):
        # Sin .upper() a secas: «GBp» (peniques, el quote de Londres) no es «GBP».
        if not value:
            return value
        if not is_currency_code(value):
            raise ValueError("Moneda no reconocida (ISO 4217 o subunidad como GBp)")
        return canonical_currency_code(value)

    @field_validator("conviction", "proposed_entry", "stop", "target", "quantity", mode="before")
    @classmethod
    def persisted_precision(cls, value, info):
        try:
            decimal = Decimal(str(value))
            if not decimal.is_finite():
                raise ValueError("El número debe ser finito")
            quantum = Decimal("0.0001") if info.field_name == "conviction" else Decimal("0.000001")
            normalized = decimal.quantize(quantum, rounding=ROUND_HALF_UP)
            if info.field_name != "conviction" and normalized >= Decimal("100000000000000"):
                raise ValueError("El número excede la precisión persistida")
            return normalized
        except (InvalidOperation, TypeError) as exc:
            raise ValueError("Número fuera de la precisión persistida") from exc

    @model_validator(mode="after")
    def valid_levels(self):
        if self.direction == "long" and not self.stop < self.proposed_entry < self.target:
            raise ValueError("Long: stop < entrada propuesta < objetivo")
        if self.direction == "short" and not self.target < self.proposed_entry < self.stop:
            raise ValueError("Short: objetivo < entrada propuesta < stop")
        return self
