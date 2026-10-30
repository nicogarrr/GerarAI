"""Un solo «valor justo» por ticker, con procedencia explícita.

Antes cada pantalla elegía el suyo: la watchlist comparaba con la última tesis
publicada (``ThesisVersion.expected_value``) y el inicio/screener/ficha pedían
al motor (``/api/valuation/{ticker}``). El mismo ticker podía salir
infravalorado en una página y sobrevalorado en otra.

Este servicio es la única fuente. Reúne los dos candidatos y aplica SIEMPRE la
misma precedencia (``PRECEDENCE``):

1. ``tesis``: tesis PUBLICADA con inputs trazables y de menos de
   ``THESIS_MAX_AGE_DAYS`` días. Es la cifra revisada y con la que se decide.
2. ``motor``: valoración del motor publicable (todos los inputs con fuente).
3. ``tesis`` antigua: tesis publicada de más de ``THESIS_MAX_AGE_DAYS`` días
   (se marca ``stale=True``); sigue siendo una cifra revisada.
4. ``motor_orientativo``: el motor tiene número pero no es publicable.

Sin ninguno: ``value=None`` y ``source=None``. Nunca se inventa una cifra.

Dos cortes adicionales del lado del motor (propuesta (b) del informe de valor
justo, 2026-10-30):

* Si la ULTIMA corrida persistida del motor es ``insufficient_data`` no se
  sirve el numero de una corrida anterior: la ultima dice que con los datos
  actuales no hay valor calculable. La lectura sale «Sin valor justo» con la
  razon (los inputs que faltan, del ``calculation_trace``).
* Un borrador orientativo (``draft``) caduca como una tesis: pasados
  ``THESIS_MAX_AGE_DAYS`` dias sin recalcular no se sirve (un RKLB con
  «VJ -94 % motor orient.» salia de un borrador viejo sin caducidad).
  La lectura sale «Sin valor justo» con la razon. Las valoraciones
  ``final`` (publicables) no caducan por esta regla.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Company, ThesisVersion, ValuationModel, ValuationOutput
from app.services.thesis_publication_gate import thesis_withheld_reasons

THESIS_MAX_AGE_DAYS = 180
PRECEDENCE = ("tesis_vigente", "motor_publicable", "tesis_antigua", "motor_orientativo")
PRECEDENCE_TEXT = (
    "Tesis publicada (< 180 días) > motor publicable > tesis publicada antigua "
    "> motor orientativo"
)


@dataclass(frozen=True)
class Candidate:
    value: float
    as_of: date | None
    publishable: bool = True
    thesis_version: int | None = None


@dataclass(frozen=True)
class EngineBlock:
    """La ultima corrida del motor no sirvio cifra: motivo declarado.

    ``kind``: "insufficient_data" (la corrida no pudo calcular) o
    "draft_stale" (borrador orientativo mas viejo que ``max_age_days``).
    """

    kind: str
    reason: str
    missing_inputs: tuple[str, ...] = ()
    as_of: date | None = None


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _positive(raw: object) -> float | None:
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    # inf ("Infinity" en un payload JSON) tampoco es un valor justo.
    return value if math.isfinite(value) and value > 0 else None


def choose(
    thesis: Candidate | None,
    engine: Candidate | None,
    *,
    today: date | None = None,
    max_age_days: int = THESIS_MAX_AGE_DAYS,
    engine_block: EngineBlock | None = None,
) -> dict:
    """Aplica la precedencia. Función pura: la usan todos los consumidores.

    Un candidato de motor ORIENTATIVO (``publishable=False``) caduca a los
    ``max_age_days`` como una tesis; sin fecha no se puede afirmar que sea
    reciente y tampoco se sirve. ``engine_block`` documenta por que la
    ultima corrida del motor no sirvio cifra (p. ej. ``insufficient_data``)
    y su razon acompaña al «Sin valor justo».
    """
    today = today or date.today()
    thesis_age = (
        (today - thesis.as_of).days if thesis is not None and thesis.as_of is not None else None
    )
    # Sin fecha no se puede afirmar que sea reciente: cuenta como antigua.
    thesis_fresh = thesis is not None and thesis_age is not None and thesis_age <= max_age_days
    engine_age = (
        (today - engine.as_of).days if engine is not None and engine.as_of is not None else None
    )
    engine_orientative_fresh = (
        engine is not None and engine_age is not None and engine_age <= max_age_days
    )

    if thesis is not None and thesis_fresh:
        return _reading("tesis", thesis, stale=False, rule="tesis_vigente")
    if engine is not None and engine.publishable:
        return _reading("motor", engine, stale=False, rule="motor_publicable")
    if thesis is not None:
        return _reading("tesis", thesis, stale=True, rule="tesis_antigua")
    if engine is not None and engine_orientative_fresh:
        return _reading("motor_orientativo", engine, stale=False, rule="motor_orientativo")
    if engine_block is not None:
        reason = engine_block.reason
        missing_inputs = list(engine_block.missing_inputs)
    elif engine is not None:
        # Borrador orientativo caducado (o sin fecha): no se sirve el numero.
        age_text = (
            f" de hace {engine_age} dias (> {max_age_days})"
            if engine_age is not None
            else " sin fecha"
        )
        reason = (
            f"La última valoración del motor es un borrador orientativo{age_text}: "
            "no se sirve sin recalcular."
        )
        missing_inputs = []
    else:
        reason = None
        missing_inputs = []
    return {
        "value": None,
        "source": None,
        "label": "Sin valor justo",
        "publishable": False,
        "as_of": None,
        "thesis_version": None,
        "stale": False,
        "rule": None,
        "reason": reason,
        "missing_inputs": missing_inputs,
    }


def _reading(source: str, candidate: Candidate, *, stale: bool, rule: str) -> dict:
    if source == "tesis":
        label = f"Tesis publicada v{candidate.thesis_version}"
        if stale:
            label += " (antigua)"
    elif source == "motor":
        label = "Motor de valoración"
    else:
        label = "Motor de valoración (orientativo)"
    return {
        "value": round(candidate.value, 4),
        "source": source,
        "label": label,
        # Una tesis publicada es una cifra final; el motor solo si es publicable.
        "publishable": source != "motor_orientativo",
        "as_of": candidate.as_of.isoformat() if candidate.as_of else None,
        "thesis_version": candidate.thesis_version,
        "stale": stale,
        "rule": rule,
        "reason": None,
        "missing_inputs": [],
    }


def thesis_candidates(db: Session, company_ids: Iterable[int]) -> dict[int, Candidate]:
    """Última tesis publicada con valor y modelo actual publicable (fail-closed)."""
    ids = list(company_ids)
    if not ids:
        return {}
    ranked = select(
        ThesisVersion.id,
        func.row_number().over(
            partition_by=ThesisVersion.company_id, order_by=ThesisVersion.version.desc()
        ).label("rank"),
    ).where(
        ThesisVersion.company_id.in_(ids),
        ThesisVersion.status == "published",
        ThesisVersion.expected_value.isnot(None),
        *tenant_filters(db, ThesisVersion),
    ).subquery()
    rows = db.scalars(
        select(ThesisVersion)
        .join(ranked, ThesisVersion.id == ranked.c.id)
        .where(ranked.c.rank == 1)
    ).all()
    reasons = thesis_withheld_reasons(db, list(rows))
    out: dict[int, Candidate] = {}
    for row in rows:
        if reasons[row.id]:
            continue  # el archivo no es evidencia de una valoración publicable actual
        basis = row.valuation_basis if isinstance(row.valuation_basis, dict) else {}
        value = listed_value(basis, fallback={"expected_value": row.expected_value})
        if value is None:
            continue
        out[int(row.company_id)] = Candidate(
            value=value,
            as_of=_as_date(row.updated_at) or _as_date(row.created_at),
            publishable=True,
            thesis_version=int(row.version),
        )
    return out


def listed_value(source: object, *, fallback: dict | None) -> float | None:
    """Valor por acción COTIZADA (lo que se compara con el precio del ticker).

    Los motores calculan por acción ORDINARIA del filing; para un ADR
    (``adr_ratio``) el valor comparable con su precio es ``listed_share_values``
    (ordinaria x N). Antes se publicaba el valor por ordinaria como valor
    justo del ADR y el margen de seguridad salía con error xN (BABA: 1/8).
    Un ADR sin valores por ADR no tiene valor comparable: None (N/D).
    """
    if not isinstance(source, dict):
        return None
    listed = source.get("listed_share_values")
    if isinstance(listed, dict):
        for key in ("expected", "base"):
            value = _positive(listed.get(key))
            if value is not None:
                return value
    if source.get("adr_ratio"):
        return None
    if fallback is None:
        return None
    for key in ("expected_value", "base_value"):
        value = _positive(fallback.get(key))
        if value is not None:
            return value
    return None


def _engine_value(payload: object) -> float | None:
    if not isinstance(payload, dict):
        return None
    return listed_value(payload, fallback=payload)


def _engine_block(model: ValuationModel) -> EngineBlock:
    """Por que la ultima corrida ``insufficient_data`` no sirvio cifra.

    Los inputs que faltan y el motivo los escribio el motor en el
    ``calculation_trace`` al persistir (``insufficient_result``); se leen tal
    cual, nunca se reconstruyen aqui.
    """
    trace = model.calculation_trace if isinstance(model.calculation_trace, dict) else {}
    missing = tuple(str(item) for item in trace.get("missing_inputs") or [] if item)
    detail = str(trace.get("reason") or "").strip()
    if missing:
        detail = "faltan " + ", ".join(missing)
    if not detail:
        detail = "el motor no pudo calcular un valor con los datos disponibles"
    as_of = _as_date(model.created_at)
    when = f" del {as_of.isoformat()}" if as_of else ""
    return EngineBlock(
        kind="insufficient_data",
        reason=f"La última valoración del motor{when} no dio cifra: {detail}.",
        missing_inputs=missing,
        as_of=as_of,
    )


def persisted_engine_readings(
    db: Session, company_ids: Iterable[int]
) -> tuple[dict[int, Candidate], dict[int, EngineBlock]]:
    """Última corrida PERSISTIDA del motor por empresa (lectura barata, por lotes).

    No recalcula: la watchlist pide hasta 60 tickers y el motor completo por
    ticker es caro. Para un solo ticker, ``resolve_fair_value(live=True)``.

    La ultima corrida manda SEA CUAL SEA SU ESTADO: si es
    ``insufficient_data`` no se resucita el numero de una corrida anterior
    (un borrador viejo seguia sirviendose como «motor orientativo»); la
    empresa queda sin candidato y con su :class:`EngineBlock`. La caducidad
    de los borradores orientativos se aplica en ``choose`` (misma regla para
    la via por lotes y la individual).
    """
    ids = list(company_ids)
    if not ids:
        return {}, {}
    ranked = select(
        ValuationModel.id,
        func.row_number().over(
            partition_by=ValuationModel.company_id, order_by=ValuationModel.version.desc()
        ).label("rank"),
    ).where(
        ValuationModel.company_id.in_(ids),
        ValuationModel.status.in_(("final", "draft", "insufficient_data")),
        *tenant_filters(db, ValuationModel),
    ).subquery()
    models = db.scalars(
        select(ValuationModel)
        .join(ranked, ValuationModel.id == ranked.c.id)
        .where(ranked.c.rank == 1)
    ).all()
    if not models:
        return {}, {}
    blocks = {
        int(model.company_id): _engine_block(model)
        for model in models
        if model.status == "insufficient_data"
    }
    by_model = {model.id: model for model in models if model.status != "insufficient_data"}
    outputs = (
        db.scalars(
            select(ValuationOutput).where(ValuationOutput.valuation_model_id.in_(list(by_model)))
        ).all()
        if by_model
        else []
    )
    out: dict[int, Candidate] = {}
    for output in outputs:
        model = by_model[output.valuation_model_id]
        company_id = int(model.company_id)
        if company_id in out:
            continue
        value = _engine_value(output.output_payload)
        if value is None:
            continue
        out[company_id] = Candidate(
            value=value,
            as_of=_as_date(model.created_at),
            publishable=model.status == "final",
        )
    return out, blocks


def persisted_engine_candidates(db: Session, company_ids: Iterable[int]) -> dict[int, Candidate]:
    """Solo los candidatos de :func:`persisted_engine_readings` (contrato previo)."""
    candidates, _blocks = persisted_engine_readings(db, company_ids)
    return candidates


def resolve_fair_values(
    db: Session, companies: Iterable[Company], *, today: date | None = None
) -> dict[int, dict]:
    """Valor justo por empresa (por lotes, sin recalcular el motor)."""
    companies = list(companies)
    ids = [int(company.id) for company in companies]
    theses = thesis_candidates(db, ids)
    engines, blocks = persisted_engine_readings(db, ids)
    out: dict[int, dict] = {}
    for company in companies:
        reading = choose(
            theses.get(int(company.id)),
            engines.get(int(company.id)),
            today=today,
            engine_block=blocks.get(int(company.id)),
        )
        reading["ticker"] = str(company.ticker).upper()
        reading["currency"] = company.currency
        out[int(company.id)] = reading
    return out


def resolve_fair_value(
    db: Session, company: Company, *, live: bool = True, today: date | None = None
) -> dict:
    """Valor justo de un ticker. Con ``live`` recalcula el motor si hace falta.

    El motor solo se calcula cuando la tesis no basta por sí sola (no hay tesis
    vigente), para no pagar el cálculo completo cuando no va a ganar.
    """
    today = today or date.today()
    thesis = thesis_candidates(db, [int(company.id)]).get(int(company.id))
    engine: Candidate | None = None
    block: EngineBlock | None = None
    thesis_fresh = (
        thesis is not None
        and thesis.as_of is not None
        and (today - thesis.as_of).days <= THESIS_MAX_AGE_DAYS
    )
    if not thesis_fresh:
        if live:
            from app.services.valuation_service import ValuationService

            try:
                result = ValuationService().value_company(db, company)
            except Exception:  # noqa: BLE001 - un motor caído degrada a «sin valor»
                result = {}
            value = _engine_value(result)
            if value is not None:
                engine = Candidate(
                    value=value,
                    as_of=today,
                    publishable=bool(result.get("publishable")),
                )
            elif result.get("status") == "insufficient_data":
                # El motor respondio: con los datos actuales no hay cifra.
                # La razon (inputs que faltan) viaja con el «Sin valor justo».
                trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
                missing = tuple(
                    str(item)
                    for item in result.get("missing_inputs") or trace.get("missing_inputs") or []
                    if item
                )
                detail = str(trace.get("reason") or "").strip()
                if missing:
                    detail = "faltan " + ", ".join(missing)
                if not detail:
                    detail = "el motor no pudo calcular un valor con los datos disponibles"
                block = EngineBlock(
                    kind="insufficient_data",
                    reason=f"La última valoración del motor no dio cifra: {detail}.",
                    missing_inputs=missing,
                    as_of=today,
                )
        else:
            engines, blocks = persisted_engine_readings(db, [int(company.id)])
            engine = engines.get(int(company.id))
            block = blocks.get(int(company.id))
    reading = choose(thesis, engine, today=today, engine_block=block)
    reading["ticker"] = str(company.ticker).upper()
    reading["currency"] = company.currency
    return reading
