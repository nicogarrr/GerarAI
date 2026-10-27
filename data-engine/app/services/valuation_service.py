"""Company valuation orchestration — engine registry, no bootstrap fair values."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.errors import redact_secrets
from app.models import Company, MarketPrice, Position, ValuationModel, ValuationOutput
from app.valuation.currency import listing_quote_unit, to_major_units
from app.valuation.engines import resolve, resolve_engine_key
from app.valuation.engines.base import MODEL_VERSION, apply_publication_blockers
from app.valuation.point_in_time import (
    PRECISION_UNKNOWN,
    assert_period_no_lookahead,
    resolve_as_of,
)


def _free_data_trace(db: Session, company: Company) -> dict | None:
    """Best-effort: expone metadata.free_data.recent_filings en el trace.

    Lee los Document de la compañía y devuelve los recent_filings del
    primero que los tenga. Nunca lanza excepciones.
    """
    try:
        from app.models import Document

        docs = list(
            db.scalars(
                select(Document).where(Document.company_id == company.id).limit(20)
            ).all()
        )
        for doc in docs:
            meta = getattr(doc, "metadata_", None) or {}
            free_data = meta.get("free_data") or {}
            recent_filings = free_data.get("recent_filings") or []
            if recent_filings:
                return {"recent_filings": recent_filings}
        return None
    except Exception:
        return None


def _assert_no_lookahead_guard(valuation: dict, *, as_of: date | None = None) -> None:
    """Falla cerrado ante periodos futuros y deja rastro del cutoff aplicado.

    Cada periodo se contrasta con la PRECISION que el propio periodo declare: un
    ``"2025-09-30:FY"`` de la ingesta SEC/ESEF se compara contra su fecha de
    cierre, no contra su ano. Comparar solo el ano admitia cierres meses en el
    futuro siempre que coincidieran con el ano del cutoff (con as_of 2025-03-31,
    un "2025-09-30:FY" pasaba porque 2025 > 2025 es falso).

    Lo que no se puede interpretar ("FY", "unknown") no dispara error, pero se
    registra como opaco en ``trace["point_in_time"]``: la cobertura del guard
    tiene que poder auditarse, que es como una comprobacion ciega se hizo pasar
    por cobertura. Ese bloque incluye de donde salio el cutoff, porque un as_of
    deducido (hoy) en vez de pedido tiene que ser distinguible al leer una
    valoracion persistida.
    """
    trace = valuation.get("trace")
    if not isinstance(trace, MutableMapping):
        # Sin `or {}`: un trace vacio es un Mapping valido y hay que auditarlo
        # sobre el dict de verdad, no sobre una copia que se pierde al salir.
        return

    resolution = resolve_as_of(as_of=as_of, valuation=valuation, trace=trace)
    cutoff = resolution.cutoff

    periods: dict[str, object] = {}
    raw_periods = trace.get("periods")
    if isinstance(raw_periods, Mapping):
        periods.update({str(label): value for label, value in raw_periods.items()})

    snapshot = trace.get("snapshot")
    if isinstance(snapshot, Mapping):
        for key in ("as_of", "income_statement", "balance_sheet", "shares"):
            if snapshot.get(key) is not None:
                periods.setdefault(f"snapshot.{key}", snapshot[key])

    by_precision: dict[str, int] = {}
    opaque_periods: list[str] = []
    for label, raw_period in periods.items():
        bounds = assert_period_no_lookahead(
            as_of=cutoff, period=raw_period, label=f"valuation {label}"
        )
        by_precision[bounds.precision] = by_precision.get(bounds.precision, 0) + 1
        if bounds.precision == PRECISION_UNKNOWN:
            opaque_periods.append(f"valuation {label} {raw_period}")

    trace["point_in_time"] = {
        "as_of": cutoff.isoformat(),
        "as_of_source": resolution.source,
        "as_of_inferred": resolution.inferred,
        "periods_checked": len(periods),
        "by_precision": by_precision,
        "opaque_periods": opaque_periods,
    }


@dataclass(frozen=True)
class ModelPrice:
    """Precio del modelo en la divisa PRINCIPAL del listado, con su fecha."""

    value: float
    currency: str
    as_of: date | None
    source: str  # "market_close" | "position_mark"


def resolve_model_price(
    db: Session, company_id: int, as_of: date | None = None
) -> ModelPrice | None:
    """El precio real mas FRESCO del valor, en unidad principal; None si no hay.

    Candidatos: el ultimo cierre de ``MarketPrice`` (``date <= as_of`` con
    cutoff) y el mark de una posicion ABIERTA (``quantity > 0``), con la fecha
    ``Position.as_of`` que escriben la reconstruccion, IBKR y el refresco de
    mercado. Gana el mas reciente; a igual fecha, el cierre oficial. Un mark
    sin fecha fiable (fila manual) solo sirve si no hay ningun cierre. Antes se
    preferia el mark de cualquier fila de posicion (incluida una cerrada,
    elegida con ``limit(1)`` sin orden) aunque hubiera un cierre mas nuevo.

    Unidades: el cierre se guarda como lo da el proveedor (Londres en
    peniques); aqui se pasa a la divisa principal del listado (GBX/100 ->
    GBP), igual que el mark (``Position.currency``). Con cutoff el mark no se
    usa: es el precio de la posicion HOY, no a esa fecha.
    """
    company = db.get(Company, company_id)
    ticker = company.ticker if company is not None else None
    company_currency = company.currency if company is not None else None
    quote_unit = listing_quote_unit(ticker, company_currency)

    close: ModelPrice | None = None
    price_query = select(MarketPrice).where(MarketPrice.company_id == company_id)
    if as_of is not None:
        price_query = price_query.where(MarketPrice.date <= as_of)
    market_price = db.scalar(price_query.order_by(desc(MarketPrice.date)).limit(1))
    if market_price and market_price.close and float(market_price.close) > 0:
        converted = to_major_units(market_price.close, quote_unit)
        if converted is not None:
            close = ModelPrice(
                value=converted.value,
                currency=converted.currency,
                as_of=market_price.date,
                source="market_close",
            )

    mark: ModelPrice | None = None
    if as_of is None:
        position = db.scalar(
            select(Position)
            .where(
                Position.company_id == company_id,
                Position.quantity > 0,
                Position.market_price > 0,
            )
            .order_by(desc(Position.as_of), desc(Position.id))
            .limit(1)
        )
        if position is not None:
            converted = to_major_units(
                position.market_price, position.currency or quote_unit
            )
            if converted is not None and converted.value > 0:
                # Una fila "manual" toma ``as_of`` del default de la columna
                # (hoy al insertarla): no es la fecha del precio (F348). Solo
                # los marks del libro, IBKR o el refresco declaran fecha.
                dated = (position.source or "manual") != "manual"
                mark = ModelPrice(
                    value=converted.value,
                    currency=converted.currency,
                    as_of=position.as_of if dated else None,
                    source="position_mark",
                )

    if close is None:
        return mark
    if mark is None:
        return close
    if mark.as_of is not None and close.as_of is not None and mark.as_of > close.as_of:
        return mark
    return close


def _position_price(
    db: Session, company_id: int, as_of: date | None = None
) -> float | None:
    """Return a real market price or None. Never invent a placeholder price.

    Ver :func:`resolve_model_price`: el mas fresco, en unidad principal."""
    resolved = resolve_model_price(db, company_id, as_of)
    return resolved.value if resolved is not None else None


def _position_price_as_of(
    db: Session, company_id: int, as_of: date | None = None
) -> str | None:
    """Fecha (ISO) del precio que ``_position_price`` resuelve, con la misma
    precedencia. None si no hay precio o la fuente no declara fecha. La ficha
    lo usa para rotular el precio del modelo con su fecha, nunca como precio
    actual."""
    resolved = resolve_model_price(db, company_id, as_of)
    if resolved is None or resolved.as_of is None:
        return None
    return resolved.as_of.isoformat()


class ValuationService:
    def value_company(
        self, db: Session, company: Company, *, as_of: date | None = None
    ) -> dict:
        current_price = _position_price(db, company.id, as_of)
        engine = resolve(company)
        context = engine.build_context(db, company, current_price, as_of)
        # Blocker enforcement lives here as well as in the engines: this is the
        # function every consumer goes through (thesis, red team, snapshot,
        # persistence), and a result that carries publication blockers must
        # never reach them labelled as a final valuation.
        result = apply_publication_blockers(engine.value(context))

        # Ensure contract fields always present for API / thesis consumers.
        result.setdefault("status", "ok")
        result.setdefault("publishable", result.get("status") == "ok")
        result.setdefault("missing_inputs", [])
        result.setdefault("reverse_dcf", {})
        result.setdefault("sensitivity", {"rows": []})
        result.setdefault("moat", {})
        try:
            from app.services.moat_service import MoatService

            result["moat"] = MoatService().assess(
                db, company, persist=False
            )
        except Exception as exc:
            result["moat"] = {
                "status": "unavailable",
                "moats": [],
                "error": redact_secrets(str(exc)),
            }
        result["trace"] = result.get("trace") or {}
        result["trace"].setdefault("engine", resolve_engine_key(company))
        result["trace"].setdefault("model_version", MODEL_VERSION)
        result["trace"]["resolved_engine"] = resolve_engine_key(company)
        free_data = _free_data_trace(db, company)
        if free_data is not None:
            result["trace"]["free_data"] = free_data
        # El guard se ejecuta aqui, antes de que el resultado llegue a thesis,
        # red team, snapshot o persistencia, y graba en el trace con que cutoff
        # se evaluo y con que precision se comprobo cada periodo.
        _assert_no_lookahead_guard(result, as_of=as_of)

        if current_price is None:
            result["trace"]["price_status"] = "missing_market_price"
            if result.get("margin_of_safety") is not None:
                # Keep MOS only when price exists; engines already return None.
                pass
            if result.get("status") == "ok" and result.get("publishable"):
                # Values may exist but MOS / reverse DCF incomplete without price.
                result["trace"]["incomplete_without_price"] = True
        else:
            result["trace"]["price_status"] = "ok"

        # El precio del modelo es un snapshot (posicion o ultimo cierre en
        # DB), no la cotizacion en vivo: la ficha lo rotula con esta fecha.
        # La fecha es best-effort: sin ella, None honesto (el precio ya esta).
        try:
            resolved_price = resolve_model_price(db, company.id, as_of)
        except Exception:  # noqa: BLE001 - la fecha nunca rompe la valoracion
            resolved_price = None
        result["trace"]["price_as_of"] = (
            resolved_price.as_of.isoformat()
            if resolved_price is not None and resolved_price.as_of is not None
            else None
        )
        # Divisa PRINCIPAL del precio (CGEO.L: GBP, ya dividido entre 100) y
        # de donde sale: el cierre o el mark de la posicion, el mas fresco.
        result["trace"]["price_currency"] = (
            resolved_price.currency if resolved_price is not None else None
        )
        result["trace"]["price_source"] = (
            resolved_price.source if resolved_price is not None else None
        )

        return result

    def persist_output(
        self,
        db: Session,
        company: Company,
        valuation: dict,
        *,
        commit: bool = True,
    ) -> ValuationModel | None:
        if not valuation.get("publishable") and valuation.get("status") == "insufficient_data":
            # Persist a draft trace so audits can show why valuation was blocked.
            status = "insufficient_data"
        else:
            status = "final" if valuation.get("publishable") else "draft"

        latest = db.scalar(
            select(ValuationModel)
            .where(ValuationModel.company_id == company.id)
            .order_by(desc(ValuationModel.version))
            .limit(1)
        )
        version = (latest.version + 1) if latest else 1
        model = ValuationModel(
            company_id=company.id,
            model_type=valuation.get("model_type") or company.valuation_model,
            version=version,
            status=status,
            calculation_trace=valuation.get("trace") or {},
        )
        db.add(model)
        db.flush()

        for scenario, key in [("bear", "bear_value"), ("base", "base_value"), ("bull", "bull_value")]:
            raw = valuation.get(key)
            if raw is None:
                continue
            db.add(
                ValuationOutput(
                    valuation_model_id=model.id,
                    scenario=scenario,
                    value_per_share=Decimal(str(raw)),
                    output_payload=valuation,
                )
            )
        if commit:
            db.commit()
            db.refresh(model)
        else:
            db.flush()
        return model
