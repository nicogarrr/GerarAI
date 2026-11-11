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

import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.i18n import current_language
from app.core.local_date import as_date as _as_date
from app.core.tenancy import tenant_filters
from app.models import Company, ThesisVersion, ValuationModel, ValuationOutput
from app.services.date_format import readable_date
from app.services.thesis_publication_gate import thesis_withheld_reasons

logger = logging.getLogger(__name__)

THESIS_MAX_AGE_DAYS = 180
PRECEDENCE = (
    "tesis_vigente",
    "motor_publicable",
    "tesis_inputs_nuevas",
    "tesis_modelo_anterior",
    "tesis_antigua",
    "motor_orientativo",
)
PRECEDENCE_TEXT = (
    "Tesis publicada (< 180 días, con inputs y motor vigentes) > motor publicable "
    "> tesis desplazada (inputs más nuevos / motor de otra versión, servida marcada) "
    "> tesis publicada antigua > motor orientativo"
)


@dataclass(frozen=True)
class Candidate:
    value: float
    as_of: date | None
    publishable: bool = True
    thesis_version: int | None = None
    # La corrida usó piezas del puente resueltas cruzando fuentes (deuda neta,
    # acciones): la etiqueta lo dice («con inputs estimados»).
    estimated_inputs: tuple[str, ...] = ()
    # Valor con método (capex normalizado / DCF multietapa): la etiqueta del
    # motor viaja con la cifra para que nunca se lea como un dato reportado.
    method_label: str | None = None
    # Vigencia de la tesis frente a sus insumos y al motor (solo candidatos
    # tesis). None = sin evidencia en ningún sentido (no desplaza: la cifra
    # revisada no se esconde por no poder comprobar); False = desactualizada
    # (inputs más nuevos que la tesis / motor de otra versión) y la tesis ya
    # no gana limpia: el motor publicable la desplaza con el motivo visible.
    inputs_fresh: bool | None = None
    model_current: bool | None = None


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
    absence: str | None = None,
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

    # Una tesis vigente por antigüedad aún puede estar DESPLAZADA: hay inputs
    # más recientes que ella (``inputs_fresh is False``) o su valoración salió
    # de otra versión del motor (``model_current is False``). Sin evidencia en
    # ningún sentido (None) la tesis no se desplaza: la cifra revisada no se
    # esconde por no poder comprobar. Si la tesis pierde, el motivo viaja en
    # la lectura (``reason`` / ``thesis_displaced``): nunca se oculta por qué.
    thesis_displaced_cause: str | None = None
    if thesis is not None and thesis_fresh:
        if thesis.inputs_fresh is False:
            thesis_displaced_cause = "inputs_nuevos"
        elif thesis.model_current is False:
            thesis_displaced_cause = "modelo_anterior"
    if thesis is not None and thesis_fresh and thesis_displaced_cause is None:
        return _reading("tesis", thesis, stale=False, rule="tesis_vigente")
    if engine is not None and engine.publishable:
        reading = _reading("motor", engine, stale=False, rule="motor_publicable")
        if thesis is not None and thesis_displaced_cause is not None:
            reading["thesis_displaced"] = {
                "version": thesis.thesis_version,
                "cause": thesis_displaced_cause,
            }
            reading["reason"] = _displaced_reason(thesis, thesis_displaced_cause)
        return reading
    if thesis is not None and thesis_displaced_cause is not None:
        rule = (
            "tesis_inputs_nuevas"
            if thesis_displaced_cause == "inputs_nuevos"
            else "tesis_modelo_anterior"
        )
        reading = _reading("tesis", thesis, stale=True, rule=rule)
        reading["reason"] = _displaced_reason(thesis, thesis_displaced_cause)
        return reading
    if thesis is not None:
        return _reading("tesis", thesis, stale=True, rule="tesis_antigua")
    if engine is not None and engine_orientative_fresh:
        return _reading("motor_orientativo", engine, stale=False, rule="motor_orientativo")
    if engine_block is not None:
        reason = engine_block.reason
        missing_inputs = list(engine_block.missing_inputs)
    elif engine is not None:
        # Borrador orientativo caducado (o sin fecha): no se sirve el numero.
        if current_language() == "en":
            age_text = (
                f" from {engine_age} {'day' if engine_age == 1 else 'days'} ago (> {max_age_days})"
                if engine_age is not None else " with no date"
            )
            reason = (
                f"The latest engine valuation is an indicative draft{age_text}: "
                "it is withheld until recalculated."
            )
        else:
            age_text = (
                f" de hace {engine_age} {'día' if engine_age == 1 else 'días'} (> {max_age_days})"
                if engine_age is not None else " sin fecha"
            )
            reason = (
                f"La última valoración del motor es un borrador orientativo{age_text}: "
                "no se sirve sin recalcular."
            )
        missing_inputs = []
    else:
        # Regla «vj-sin-candidato-v1»: ni tesis ni valoración del motor dan cifra. El «Sin valor justo» nunca
        # sale mudo: ``absence`` es el motivo exacto que arma quien consultó la base (``_no_candidate_reason``);
        # sin él, el motivo general (no hay tesis publicada ni valoración del motor).
        reason = absence or _no_candidate_reason(None, ENGINE_GAP_NO_RUN)
        missing_inputs = []
    return {
        "value": None,
        "source": None,
        "label": "No fair value" if current_language() == "en" else "Sin valor justo",
        "publishable": False,
        "as_of": None,
        "thesis_version": None,
        "stale": False,
        "rule": None,
        "reason": reason,
        "missing_inputs": missing_inputs,
    }


# Motivos del lado del motor cuando no hay candidato ni corrida ``insufficient_data`` (regla «vj-sin-candidato-v1»).
ENGINE_GAP_NO_RUN = "no_run"  # ninguna valoración del motor guardada para la empresa
ENGINE_GAP_NO_OUTPUT = "no_output"  # corrida guardada sin resultado
ENGINE_GAP_NON_POSITIVE = "non_positive"  # el resultado no trae un valor por acción positivo
ENGINE_GAP_ADR = "adr_without_listed"  # ADR sin valor por acción cotizada
ENGINE_GAP_FAILED = "failed"  # el cálculo en vivo falló
ENGINE_GAP_NO_VALUE_LIVE = "no_value_live"  # el cálculo en vivo respondió sin valor por acción positivo


@dataclass(frozen=True)
class EngineGap:
    """Por qué el motor no aporta candidato (sin ser ``insufficient_data``)."""

    kind: str
    as_of: date | None = None


def _engine_gap_text(gap: EngineGap | str, english: bool) -> str:
    gap = gap if isinstance(gap, EngineGap) else EngineGap(kind=gap)
    when = (
        (" from " if english else " del ") + readable_date(gap.as_of, "en" if english else "es")
        if gap.as_of else ""
    )
    if english:
        texts = {
            ENGINE_GAP_NO_RUN: "no engine valuation is stored for this company",
            ENGINE_GAP_NO_OUTPUT: f"the latest stored engine valuation{when} has no result",
            ENGINE_GAP_NON_POSITIVE: f"the latest stored engine valuation{when} gives no positive value per share",
            ENGINE_GAP_ADR: f"the latest stored engine valuation{when} has no value per listed share (ADR)",
            ENGINE_GAP_FAILED: "the valuation engine failed while calculating",
            ENGINE_GAP_NO_VALUE_LIVE: "the valuation engine gave no positive value per share",
        }
    else:
        texts = {
            ENGINE_GAP_NO_RUN: "no hay ninguna valoración del motor guardada para esta empresa",
            ENGINE_GAP_NO_OUTPUT: f"la última valoración del motor guardada{when} no tiene resultado",
            ENGINE_GAP_NON_POSITIVE: (
                f"la última valoración del motor guardada{when} no da un valor por acción positivo"
            ),
            ENGINE_GAP_ADR: (
                f"la última valoración del motor guardada{when} no trae valor por acción cotizada (ADR)"
            ),
            ENGINE_GAP_FAILED: "el motor de valoración falló al calcular",
            ENGINE_GAP_NO_VALUE_LIVE: "el motor de valoración no dio un valor por acción positivo",
        }
    return texts.get(gap.kind, texts[ENGINE_GAP_NO_RUN])


def _no_candidate_reason(thesis_gap: str | None, engine_gap: EngineGap | str) -> str:
    """Motivo exacto del «Sin valor justo» cuando ni la tesis ni el motor dan cifra.

    ``thesis_gap``: por qué la última tesis publicada no sirve (``thesis_candidates(gaps=...)``) o None si
    no hay ninguna tesis publicada con valor.
    """
    english = current_language() == "en"
    if thesis_gap:
        thesis_text = thesis_gap
    else:
        thesis_text = "There is no published thesis" if english else "No hay tesis publicada"
    joiner = " and " if english else " y "
    return f"{thesis_text}{joiner}{_engine_gap_text(engine_gap, english)}."


def _thesis_gap_text(row: ThesisVersion, withheld: str | None) -> str:
    english = current_language() == "en"
    if withheld:
        if english:
            from app.services.thesis_publication_gate import withheld_reason_en

            withheld = withheld_reason_en(withheld)
        detail = withheld.strip().rstrip(".")
        detail = detail[:1].lower() + detail[1:]
        if english:
            return f"The latest published thesis (v{int(row.version)}) is withheld ({detail})"
        return f"La última tesis publicada (v{int(row.version)}) está retenida ({detail})"
    if english:
        return f"The latest published thesis (v{int(row.version)}) has no value per listed share"
    return f"La última tesis publicada (v{int(row.version)}) no trae valor por acción cotizada"


def _reading(source: str, candidate: Candidate, *, stale: bool, rule: str) -> dict:
    if source == "tesis":
        label = f"Tesis publicada v{candidate.thesis_version}"
        if stale:
            label += " (antigua)"
    elif source == "motor":
        label = "Motor de valoración"
    else:
        label = "Motor de valoración (orientativo)"
    if candidate.estimated_inputs:
        label += " · con inputs estimados"
    if candidate.method_label and source != "tesis":
        label += f" · {candidate.method_label}"
    return {
        "value": round(candidate.value, 4),
        "source": source,
        "label": label,
        **({"estimated_inputs": list(candidate.estimated_inputs)} if candidate.estimated_inputs else {}),
        **({"method_label": candidate.method_label} if candidate.method_label else {}),
        # Una tesis publicada es una cifra final; el motor solo si es publicable.
        "publishable": source != "motor_orientativo",
        "as_of": candidate.as_of.isoformat() if candidate.as_of else None,
        "thesis_version": candidate.thesis_version,
        "stale": stale,
        "rule": rule,
        "reason": None,
        "missing_inputs": [],
    }


def _displaced_reason(thesis: Candidate, cause: str) -> str:
    """Por que la tesis no se sirve como cifra vigente (visible en la ficha)."""
    if current_language() == "en":
        if cause == "inputs_nuevos":
            return (
                f"Published thesis v{thesis.thesis_version} is still the reviewed figure, "
                "but newer data (filings, news or an official close) arrived after it."
            )
        return (
            f"Published thesis v{thesis.thesis_version} is still the reviewed figure, "
            "but it was valued with a previous version of the valuation engine."
        )
    if cause == "inputs_nuevos":
        return (
            f"La tesis publicada v{thesis.thesis_version} sigue siendo la cifra revisada, "
            "pero hay datos más recientes que ella (filing, noticias o un cierre oficial)."
        )
    return (
        f"La tesis publicada v{thesis.thesis_version} sigue siendo la cifra revisada, "
        "pero se valoró con una versión anterior del motor de valoración."
    )


def _thesis_input_freshness(
    db: Session, rows: list[ThesisVersion]
) -> dict[int, bool]:
    """¿Los inputs de cada tesis son anteriores o iguales a su fecha? (por lotes)

    Misma frontera que ``ThesisService.data_freshness``: hechos, noticias y
    documentos con ``updated_at`` posterior a la versión la desactualizan, y en
    precios solo cuenta una barra de CIERRE oficial posterior a la última
    sesión que la versión pudo conocer (un tick intradía no). True = vigente.
    """
    from app.models import Document, FinancialFact, MarketPrice, NewsEvent
    from app.services.thesis_service import _last_official_close_date

    anchors = {int(row.company_id): row.updated_at for row in rows}
    ids = list(anchors)
    stale: set[int] = set()
    tenant_id = db.info.get("tenant_id")
    for model in (FinancialFact, NewsEvent, Document):
        stmt = (
            select(model.company_id, func.max(model.updated_at))
            .where(model.company_id.in_(ids))
            .group_by(model.company_id)
        )
        if tenant_id is not None:
            stmt = stmt.where(model.tenant_id == tenant_id)
        for company_id, stamp in db.execute(stmt):
            anchor = anchors.get(int(company_id))
            if stamp is not None and anchor is not None and stamp > anchor:
                stale.add(int(company_id))
    pending = [row for row in rows if int(row.company_id) not in stale]
    if pending:
        price_dates = dict(
            db.execute(
                select(MarketPrice.company_id, func.max(MarketPrice.date))
                .where(
                    MarketPrice.company_id.in_([int(row.company_id) for row in pending]),
                    MarketPrice.source == "yfinance",
                )
                .group_by(MarketPrice.company_id)
            ).all()
        )
        for row in pending:
            anchor = _last_official_close_date(row.updated_at)
            official = price_dates.get(int(row.company_id))
            if anchor is not None and official is not None and official > anchor:
                stale.add(int(row.company_id))
    return {int(row.company_id): int(row.company_id) not in stale for row in rows}


def thesis_candidates(
    db: Session, company_ids: Iterable[int], *, gaps: dict[int, str] | None = None
) -> dict[int, Candidate]:
    """Última tesis publicada con valor y modelo actual publicable (fail-closed).

    ``gaps`` (opcional) recibe, por empresa, por qué su última tesis publicada no es candidata (retenida por la
    puerta de publicación o sin valor por acción cotizada): el motivo del «Sin valor justo».
    """
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
    from app.services.thesis_service import engine_stale

    freshness = _thesis_input_freshness(db, list(rows)) if rows else {}
    # engine_stale: None = versión no registrada (tesis anterior a la señal):
    # no se afirma vigente ni desactualizado y NO desplaza la cifra revisada.
    model_current: dict[int, bool | None] = {}
    for row in rows:
        basis = row.valuation_basis if isinstance(row.valuation_basis, dict) else None
        stale_flag = engine_stale(basis)
        # None = versión no registrada (tesis anterior a la señal): neutro.
        model_current[int(row.company_id)] = None if stale_flag is None else not stale_flag
    out: dict[int, Candidate] = {}
    for row in rows:
        if reasons[row.id]:
            if gaps is not None:
                gaps[int(row.company_id)] = _thesis_gap_text(row, reasons[row.id])
            continue  # el archivo no es evidencia de una valoración publicable actual
        basis = row.valuation_basis if isinstance(row.valuation_basis, dict) else {}
        value = listed_value(basis, fallback={"expected_value": row.expected_value})
        if value is None:
            if gaps is not None:
                gaps[int(row.company_id)] = _thesis_gap_text(row, None)
            continue
        out[int(row.company_id)] = Candidate(
            value=value,
            as_of=_as_date(row.updated_at) or _as_date(row.created_at),
            publishable=True,
            thesis_version=int(row.version),
            inputs_fresh=freshness.get(int(row.company_id)),
            model_current=model_current.get(int(row.company_id)),
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


def _estimated_inputs(payload: object) -> tuple[str, ...]:
    """Metricas del puente que la corrida tomó por cruce de fuentes."""
    if not isinstance(payload, dict):
        return ()
    items = payload.get("estimated_inputs") or []
    return tuple(str(i.get("metric")) for i in items if isinstance(i, dict) and i.get("metric"))


def _method_label(payload: object) -> str | None:
    """Etiqueta del método con que el motor estimó la cifra (si la hay)."""
    if not isinstance(payload, dict):
        return None
    label = payload.get("valuation_label")
    return str(label) if isinstance(label, str) and label else None


def _engine_value(payload: object) -> float | None:
    if not isinstance(payload, dict):
        return None
    return listed_value(payload, fallback=payload)


def _insufficient_reason(detail: str, missing: tuple[str, ...], *, as_of: date | None = None) -> str:
    """Localize the wrapper, keeping a persisted free-text reason verbatim."""
    english = current_language() == "en"
    if missing:
        detail = ("missing " if english else "faltan ") + ", ".join(missing)
    if not detail:
        detail = (
            "the engine could not calculate a value with the available data"
            if english else "el motor no pudo calcular un valor con los datos disponibles"
        )
    when = (
        (" from " if english else " del ") + readable_date(as_of, "en" if english else "es")
        if as_of else ""
    )
    prefix = (
        f"The latest engine valuation{when} produced no value"
        if english else f"La última valoración del motor{when} no dio cifra"
    )
    return f"{prefix}: {detail}."


def _engine_block(model: ValuationModel) -> EngineBlock:
    """Por que la ultima corrida ``insufficient_data`` no sirvio cifra.

    Los inputs que faltan y el motivo los escribio el motor en el
    ``calculation_trace`` al persistir (``insufficient_result``); se leen tal
    cual, nunca se reconstruyen aqui.
    """
    trace = model.calculation_trace if isinstance(model.calculation_trace, dict) else {}
    missing = tuple(str(item) for item in trace.get("missing_inputs") or [] if item)
    detail = str(trace.get("reason") or "").strip()
    as_of = _as_date(model.created_at)
    return EngineBlock(
        kind="insufficient_data",
        reason=_insufficient_reason(detail, missing, as_of=as_of),
        missing_inputs=missing,
        as_of=as_of,
    )


def persisted_engine_readings(
    db: Session, company_ids: Iterable[int], *, gaps: dict[int, EngineGap] | None = None
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

    ``gaps`` (opcional) recibe, por empresa sin candidato ni bloqueo, por qué el motor no aporta cifra
    (:class:`EngineGap`: sin corrida guardada, corrida sin resultado, valor no positivo o ADR sin valor cotizado).
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
        if gaps is not None:
            gaps.update({int(company_id): EngineGap(kind=ENGINE_GAP_NO_RUN) for company_id in ids})
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
    payload_gaps: dict[int, str] = {}
    for output in outputs:
        model = by_model[output.valuation_model_id]
        company_id = int(model.company_id)
        if company_id in out:
            continue
        value = _engine_value(output.output_payload)
        if value is None:
            payload = output.output_payload if isinstance(output.output_payload, dict) else {}
            adr = bool(payload.get("adr_ratio")) and not isinstance(payload.get("listed_share_values"), dict)
            payload_gaps.setdefault(company_id, ENGINE_GAP_ADR if adr else ENGINE_GAP_NON_POSITIVE)
            continue
        out[company_id] = Candidate(
            value=value,
            as_of=_as_date(model.created_at),
            publishable=model.status == "final",
            estimated_inputs=_estimated_inputs(output.output_payload),
            method_label=_method_label(output.output_payload),
        )
    if gaps is not None:
        models_by_company = {int(model.company_id): model for model in models}
        for company_id in ids:
            if company_id in out or company_id in blocks:
                continue
            model = models_by_company.get(company_id)
            if model is None:
                gaps[company_id] = EngineGap(kind=ENGINE_GAP_NO_RUN)
            else:
                gaps[company_id] = EngineGap(
                    kind=payload_gaps.get(company_id, ENGINE_GAP_NO_OUTPUT), as_of=_as_date(model.created_at)
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
    thesis_gaps: dict[int, str] = {}
    engine_gaps: dict[int, EngineGap] = {}
    theses = thesis_candidates(db, ids, gaps=thesis_gaps)
    engines, blocks = persisted_engine_readings(db, ids, gaps=engine_gaps)
    out: dict[int, dict] = {}
    for company in companies:
        company_id = int(company.id)
        reading = choose(
            theses.get(company_id),
            engines.get(company_id),
            today=today,
            engine_block=blocks.get(company_id),
            absence=_no_candidate_reason(
                thesis_gaps.get(company_id), engine_gaps.get(company_id, EngineGap(kind=ENGINE_GAP_NO_RUN))
            ),
        )
        reading["ticker"] = str(company.ticker).upper()
        reading["currency"] = company.currency
        out[int(company.id)] = reading
    return out


# TTL de la cache Redis del recalculo "live" por ticker. 15 min: la ventana
# mas corta que colapsa las cargas repetidas de Inicio (el sondeo de
# oportunidades reprobando la MISMA lista de candidatas estables intradia,
# medido 31-oct: POST del bundle de 6.959 ms en Vercel) sin cambiar la
# semantica del dato: el recalculo lee fundamentales/KPIs persistidos
# (ingesta diaria) y la ultima cotizacion en BD; la lectura por lotes
# (/fair-value) ya sirve SOLO lo persistido, asi que 15 min de margen sobre
# el single-ticker queda dentro de lo que la UI ya muestra en otras pantallas.
# Una tesis publicada dentro de la ventana puede tardar <=15 min en verse;
# la ingesta nueva idem. Sin invalidacion explicita: el TTL se autocorrige.
FAIR_VALUE_LIVE_CACHE_TTL_SECONDS = 15 * 60


def _live_cache_key(db: Session, company: Company) -> str:
    tenant = db.info.get("tenant_id")
    return f"fair_value_live:{tenant}:{int(company.id)}:{current_language()}:{date.today().isoformat()}"


def resolve_fair_value_cached(
    db: Session, company: Company, *, live: bool = True, ttl: int = FAIR_VALUE_LIVE_CACHE_TTL_SECONDS
) -> dict:
    """resolve_fair_value con cache Redis por (tenant, empresa, dia).

    El camino live recalcula el motor cuando no hay tesis fresca
    (ValuationService().value_company, el coste real); la cache evita
    recalcular lo mismo en cada carga de Inicio/watchlist. Fail-open: con
    Redis caido se calcula igual y no se propaga la excepcion. La respuesta
    cacheada y la recien calculada pasan por el mismo ciclo JSON.
    """
    import json as _json

    from app.core.cache import _redis_client  # precedente: connectors/alpha_vantage

    client = None
    key = None
    try:
        client = _redis_client()
        if client is not None:
            key = _live_cache_key(db, company)
            raw = client.get(key)
            if raw is not None:
                return _json.loads(raw)
    except Exception:  # noqa: BLE001 - cache best-effort, fail-open
        client, key = None, None
    reading = resolve_fair_value(db, company, live=live)
    if client is not None and key is not None:
        try:
            client.set(key, _json.dumps(reading, default=str), ex=max(int(ttl), 1))
        except Exception:  # noqa: BLE001 - no cachear nunca rompe la lectura
            logger.warning("fair value: escritura cache Redis fallo; se devuelve el calculo", exc_info=True)
    return reading


def resolve_fair_value(
    db: Session, company: Company, *, live: bool = True, today: date | None = None
) -> dict:
    """Valor justo de un ticker. Con ``live`` recalcula el motor si hace falta.

    El motor solo se calcula cuando la tesis no basta por sí sola (no hay tesis
    vigente), para no pagar el cálculo completo cuando no va a ganar.
    """
    today = today or date.today()
    thesis_gaps: dict[int, str] = {}
    thesis = thesis_candidates(db, [int(company.id)], gaps=thesis_gaps).get(int(company.id))
    engine: Candidate | None = None
    block: EngineBlock | None = None
    engine_gap: EngineGap = EngineGap(kind=ENGINE_GAP_NO_RUN)
    thesis_fresh = (
        thesis is not None
        and thesis.as_of is not None
        and (today - thesis.as_of).days <= THESIS_MAX_AGE_DAYS
    )
    # Tesis vigente por antigüedad pero desplazada (inputs más nuevos o motor
    # de otra versión): el motor se recalcula en vivo para disputarle la cifra.
    thesis_displaced = thesis_fresh and (
        thesis.inputs_fresh is False or thesis.model_current is False
    )
    if not thesis_fresh or thesis_displaced:
        if live:
            from app.services.valuation_service import ValuationService

            try:
                result = ValuationService().value_company(db, company)
            except Exception:  # noqa: BLE001 - un motor caído degrada a «sin valor»
                logger.warning("fair value: el motor falló al calcular %s", company.ticker, exc_info=True)
                result = {}
                engine_gap = EngineGap(kind=ENGINE_GAP_FAILED)
            else:
                engine_gap = EngineGap(
                    kind=ENGINE_GAP_ADR
                    if isinstance(result, dict) and result.get("adr_ratio")
                    and not isinstance(result.get("listed_share_values"), dict)
                    else ENGINE_GAP_NO_VALUE_LIVE
                )
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
                block = EngineBlock(
                    kind="insufficient_data",
                    reason=_insufficient_reason(detail, missing),
                    missing_inputs=missing,
                    as_of=today,
                )
        else:
            engine_gaps: dict[int, EngineGap] = {}
            engines, blocks = persisted_engine_readings(db, [int(company.id)], gaps=engine_gaps)
            engine = engines.get(int(company.id))
            block = blocks.get(int(company.id))
            engine_gap = engine_gaps.get(int(company.id), engine_gap)
    reading = choose(
        thesis,
        engine,
        today=today,
        engine_block=block,
        absence=_no_candidate_reason(thesis_gaps.get(int(company.id)), engine_gap),
    )
    reading["ticker"] = str(company.ticker).upper()
    reading["currency"] = company.currency
    return reading
