"""Read only the JSON fields used by persisted fair-value candidates."""
from sqlalchemy import JSON, case, cast, column, func, literal, select, true

from app.models import ValuationOutput


def output_reading_statement(db, model_ids):
    payload = ValuationOutput.output_payload
    sources = []
    if db.get_bind().dialect.name == "postgresql":
        empty = cast(literal("{}"), JSON)
        inputs = func.json_to_record(case(
            (func.json_typeof(payload) == "object", payload), else_=empty,
        )).table_valued(
            column("listed_share_values", JSON), column("adr_ratio", JSON),
            column("expected_value", JSON), column("base_value", JSON),
            column("estimated_inputs", JSON), column("valuation_label", JSON),
            column("warnings", JSON),
        ).render_derived(with_types=True).lateral()
        fields = tuple(inputs.c)
        sources = [inputs]
    else:
        fields = tuple(payload[key] for key in (
            "listed_share_values", "adr_ratio", "expected_value", "base_value",
            "estimated_inputs", "valuation_label", "warnings",
        ))
    statement = select(ValuationOutput.valuation_model_id, *fields).where(
        ValuationOutput.valuation_model_id.in_(model_ids),
    )
    for source in sources:
        statement = statement.join(source, true())
    return statement


def reading_payload(row):
    return dict(zip((
        "listed_share_values", "adr_ratio", "expected_value", "base_value",
        "estimated_inputs", "valuation_label", "warnings",
    ), row[1:], strict=True))
