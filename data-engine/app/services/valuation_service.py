"""Company valuation orchestration — engine registry, no bootstrap fair values."""

from __future__ import annotations

import logging
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.errors import redact_secrets
from app.models import Company, MarketPrice, Position, ValuationModel, ValuationOutput
from app.services.price_units import listing_price, price_in_currency
from app.services.split_adjustment import split_after_price, split_events_by_company
from app.valuation.currency import (
    listing_currency,
    listing_quote_unit,
    normalize_currency,
    reporting_currencies,
    resolve_fx,
    scale_per_share_outputs,
    to_major_units,
)
from app.valuation.engines import resolve, resolve_engine_key
from app.valuation.engines.base import (
    MODEL_VERSION,
    ValuationContext,
    ValuationEngine,
    apply_publication_blockers,
    insufficient_result,
)
from app.valuation.margin_convention import MARGIN_OF_SAFETY_CONVENTION
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

        docs = list(db.scalars(select(Document).where(Document.company_id == company.id).limit(20)).all())
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
        bounds = assert_period_no_lookahead(as_of=cutoff, period=raw_period, label=f"valuation {label}")
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


def resolve_model_price(db: Session, company_id: int, as_of: date | None = None) -> ModelPrice | None:
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
    ticker = getattr(company, "ticker", None)
    company_currency = getattr(company, "currency", None)
    quote_unit = listing_quote_unit(ticker, company_currency)

    close: ModelPrice | None = None
    price_query = select(MarketPrice).where(MarketPrice.company_id == company_id)
    if as_of is not None:
        price_query = price_query.where(MarketPrice.date <= as_of)
    market_price = db.scalar(price_query.order_by(desc(MarketPrice.date)).limit(1))
    if market_price and market_price.close and float(market_price.close) > 0:
        major, _ = normalize_currency(quote_unit)
        converted = price_in_currency(
            market_price.close, quote_currency=market_price.quote_currency,
            target_currency=major, company=company,
        )
        price_currency = major
        if (
            converted is None
            and market_price.quote_currency
            and (market_price.source or "").lower() == "yfinance"
        ):
            # La divisa del precio es la de la COTIZACION que declara Yahoo
            # (SHEL.L: GBp), no la de las cuentas (USD). Se expresa en su
            # divisa principal y _reconcile_currency la pasa a la de las
            # cuentas con FX. Solo filas yfinance: las FMP/Finnhub antiguas
            # de emisores no-US llevan USD del gemelo americano (F159).
            listed = listing_price(
                market_price.close, quote_currency=market_price.quote_currency, company=company,
            )
            if listed is not None:
                converted, price_currency = listed
        if converted is not None:
            close = ModelPrice(
                value=float(converted),
                currency=price_currency,
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
            converted = to_major_units(position.market_price, position.currency or quote_unit)
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


def _position_price(db: Session, company_id: int, as_of: date | None = None) -> float | None:
    """Return a real market price or None. Never invent a placeholder price.

    Ver :func:`resolve_model_price`: el mas fresco, en unidad principal."""
    resolved = resolve_model_price(db, company_id, as_of)
    return resolved.value if resolved is not None else None


def _position_price_as_of(db: Session, company_id: int, as_of: date | None = None) -> str | None:
    """Fecha (ISO) del precio que ``_position_price`` resuelve, con la misma
    precedencia. None si no hay precio o la fuente no declara fecha. La ficha
    lo usa para rotular el precio del modelo con su fecha, nunca como precio
    actual."""
    resolved = resolve_model_price(db, company_id, as_of)
    if resolved is None or resolved.as_of is None:
        return None
    return resolved.as_of.isoformat()


def _reconcile_currency(
    db: Session,
    context: ValuationContext,
    *,
    price_currency: str,
    on: date,
) -> dict:
    """Comprueba que hechos y precio estan en la misma divisa o se pueden convertir.

    Devuelve ``status``:
    - ``"same"``: hechos y precio en la misma divisa;
    - ``"converted"``: distinta divisa con un tipo point-in-time valido
      (``price_to_reporting`` / ``reporting_to_listing`` son los factores);
    - ``"unknown"``: no hay hechos monetarios en el snapshot (no hay nada que
      comparar; el motor dira que le faltan entradas);
    - ``"blocked"``: hechos en varias divisas entre si, o sin tipo de cambio
      valido (``missing_inputs`` dice cual).
    """
    facts = getattr(getattr(context, "snapshot", None), "facts", None) or {}
    units = [getattr(fact, "unit", None) for fact in facts.values()]
    found = reporting_currencies(units)
    base: dict = {
        "price_currency": price_currency,
        "reporting_currency": None,
        "fx": None,
        "fx_date": on.isoformat(),
    }
    if not found:
        return {**base, "status": "unknown"}
    if len(found) > 1:
        return {
            **base,
            "status": "blocked",
            "reason": "currency_mismatch_in_facts",
            "reporting_currencies": sorted(found),
            "missing_inputs": ["single_reporting_currency"],
        }
    reporting = next(iter(found))
    base["reporting_currency"] = reporting
    if reporting == price_currency.upper():
        return {**base, "status": "same"}
    to_reporting = resolve_fx(db, price_currency, reporting, on)
    if to_reporting is None:
        return {
            **base,
            "status": "blocked",
            "reason": "currency_mismatch_no_fx",
            "missing_inputs": [f"fx_rate:{reporting}/{price_currency.upper()}"],
        }
    return {
        **base,
        "status": "converted",
        "fx": to_reporting.as_trace(),
        "price_to_reporting": to_reporting.rate,
        "reporting_to_listing": 1.0 / to_reporting.rate,
    }


def _currency_blocked_result(engine: ValuationEngine, context: ValuationContext, gate: dict) -> dict:
    """Resultado bloqueado: sin valores ni margen de seguridad, con el motivo."""
    company = context.company
    if gate.get("reason") == "currency_mismatch_in_facts":
        reason = (
            "Los datos financieros estan en varias divisas "
            f"({', '.join(gate.get('reporting_currencies') or [])}): no se mezclan."
        )
    else:
        reason = (
            f"Los datos estan en {gate.get('reporting_currency')} y el precio en "
            f"{gate.get('price_currency')}, y no hay tipo de cambio a "
            f"{gate.get('fx_date')} (tabla BCE): no se compara un valor y un "
            "precio en divisas distintas."
        )
    return insufficient_result(
        ticker=company.ticker,
        model_type=company.valuation_model,
        engine_key=engine.key,
        current_price=context.current_price,
        missing_inputs=list(gate.get("missing_inputs") or []),
        reason=reason,
        snapshot=context.snapshot,
        extra_trace={"currency_gate": {k: v for k, v in gate.items()}},
    )


logger = logging.getLogger(__name__)


class ValuationService:
    def value_company(self, db: Session, company: Company, *, as_of: date | None = None) -> dict:
        price_error = None
        try:
            resolved_price = resolve_model_price(db, company.id, as_of)
        except Exception as exc:  # noqa: BLE001 - sin precio, la valoracion sigue sin MOS
            price_error = type(exc).__name__
            logger.warning("Model price lookup failed company_id=%s error=%s", company.id, price_error)
            resolved_price = None
        current_price = resolved_price.value if resolved_price is not None else None
        # Ultimo cierre anterior a un split ya efectivo: su base de acciones es
        # desconocida (vieja o ya ajustada por el proveedor). El valor por
        # accion va en la base actual y el precio no se compara: MOS y DCF
        # inverso N/D hasta que se guarde un cierre posterior al split.
        price_basis_unknown = resolved_price is not None and split_after_price(
            split_events_by_company(db, [company.id]).get(company.id, []),
            resolved_price.as_of,
            as_of or date.today(),
        )
        if price_basis_unknown:
            current_price = None
        price_currency = (
            resolved_price.currency
            if resolved_price is not None
            else listing_currency(getattr(company, "ticker", None), getattr(company, "currency", None))
        )
        engine = resolve(company)
        # Acciones en la base del PRECIO: un cierre guardado antes de un split
        # (el refresco aun no ha pasado) sigue en la base vieja; ajustar las
        # acciones por ese split dividia el valor por accion entre el ratio.
        context = engine.build_context(
            db,
            company,
            current_price,
            as_of,
            price_as_of=(
                resolved_price.as_of
                if resolved_price is not None and not price_basis_unknown
                else None
            ),
        )

        # Divisas: el motor trabaja en la divisa de REPORTE de los hechos (BABA:
        # CNY) y el precio esta en la del LISTADO (ADR en USD). Comparar ambos
        # sin convertir era el error ~7x. Se convierte con el tipo de cambio de
        # la fecha del precio (point-in-time) y, si no se puede reconciliar, se
        # bloquea la valoracion en vez de publicar un margen de seguridad falso.
        fx_date = (
            resolved_price.as_of
            if resolved_price is not None and resolved_price.as_of is not None
            else (as_of or date.today())
        )
        currency_gate = _reconcile_currency(db, context, price_currency=price_currency, on=fx_date)
        if currency_gate["status"] == "blocked":
            result = _currency_blocked_result(engine, context, currency_gate)
        else:
            to_reporting = currency_gate.get("price_to_reporting")
            if to_reporting is not None and current_price is not None:
                # Precio traducido a la divisa de los hechos: el DCF, el margen
                # de seguridad y el DCF inverso se calculan en UNA sola divisa.
                context.current_price = current_price * to_reporting
            # Blocker enforcement lives here as well as in the engines: this is the
            # function every consumer goes through (thesis, red team, snapshot,
            # persistence), and a result that carries publication blockers must
            # never reach them labelled as a final valuation.
            result = apply_publication_blockers(engine.value(context))
            to_listing = currency_gate.get("reporting_to_listing")
            if to_listing is not None:
                # Valores por accion de vuelta a la divisa del listado (misma
                # tasa, invertida): MOS y crecimientos son invariantes.
                scale_per_share_outputs(result, to_listing)
                result["current_price"] = current_price
        result["value_currency"] = price_currency if currency_gate["status"] != "blocked" else None
        result["currency"] = {
            key: value
            for key, value in currency_gate.items()
            if key not in {"price_to_reporting", "reporting_to_listing"}
        }

        # Ensure contract fields always present for API / thesis consumers.
        result.setdefault("status", "ok")
        result.setdefault("publishable", result.get("status") == "ok")
        result.setdefault("missing_inputs", [])
        result.setdefault("reverse_dcf", {})
        result.setdefault("sensitivity", {"rows": []})
        result.setdefault("moat", {})
        try:
            from app.services.moat_service import MoatService

            result["moat"] = MoatService().assess(db, company, persist=False)
        except Exception as exc:
            result["moat"] = {
                "status": "unavailable",
                "moats": [],
                "error": redact_secrets(str(exc)),
            }
        result["trace"] = result.get("trace") or {}
        result["trace"].setdefault("engine", resolve_engine_key(company))
        result["trace"].setdefault("model_version", MODEL_VERSION)
        # Written only by a fresh computation, never added when reading history.
        result["trace"]["margin_of_safety_convention"] = MARGIN_OF_SAFETY_CONVENTION
        result["trace"]["resolved_engine"] = resolve_engine_key(company)
        free_data = _free_data_trace(db, company)
        if free_data is not None:
            result["trace"]["free_data"] = free_data
        # El guard se ejecuta aqui, antes de que el resultado llegue a thesis,
        # red team, snapshot o persistencia, y graba en el trace con que cutoff
        # se evaluo y con que precision se comprobo cada periodo.
        _assert_no_lookahead_guard(result, as_of=as_of)
        # Cobertura del corte por fecha de publicacion (V1): cuantos hechos
        # quedaron fuera por ser posteriores al corte o indemostrables. Sin
        # corte (filed_cutoff None) no se escribe nada.
        _snapshot = getattr(context, "snapshot", None)
        if _snapshot is not None and getattr(_snapshot, "filed_cutoff", None):
            _pit = result["trace"].get("point_in_time")
            if isinstance(_pit, MutableMapping):
                _pit["filed_cutoff"] = _snapshot.filed_cutoff
                _pit["filed_excluded_future"] = _snapshot.filed_excluded_future
                _pit["filed_excluded_unknown"] = _snapshot.filed_excluded_unknown

        if price_error is not None:
            result["trace"]["price_error"] = price_error

        if price_basis_unknown:
            result["trace"]["price_status"] = "price_basis_unknown_after_split"
            result["trace"]["price_basis_note"] = (
                "El ultimo cierre guardado es anterior a un split ya efectivo: "
                "no se sabe si esta en la base vieja o ya ajustada, asi que no "
                "se compara con el valor por accion (N/D hasta el primer cierre "
                "posterior al split)."
            )
        elif current_price is None:
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
        result["trace"]["currency"] = result["currency"]
        result["trace"]["price_as_of"] = (
            resolved_price.as_of.isoformat()
            if resolved_price is not None and resolved_price.as_of is not None
            else None
        )
        # Divisa PRINCIPAL del precio (CGEO.L: GBP, ya dividido entre 100) y
        # de donde sale: el cierre o el mark de la posicion, el mas fresco.
        result["trace"]["price_currency"] = resolved_price.currency if resolved_price is not None else None
        result["trace"]["price_source"] = resolved_price.source if resolved_price is not None else None

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
