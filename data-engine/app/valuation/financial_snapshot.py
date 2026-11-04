"""Build a temporally coherent financial snapshot for valuation inputs.

Independent per-metric "latest" queries can mix FY revenue with TTM FCF and
stale shares. This builder anchors on a primary income-statement period and
only accepts companion facts from the same economic snapshot (or a compatible
balance-sheet instant).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import case, desc, select
from sqlalchemy.orm import Session, selectinload

from app.models import Company, FinancialFact
from app.services.esef_fact_quarantine import fact_quarantine_reason
from app.services.reviewed_eps_adjustments import eligible_fact
from app.services.split_adjustment import split_factor_for_fact

# Income-statement style metrics: flows over a period. They must share the
# anchor's period, otherwise a 12-month revenue gets divided by a 9-month OCF.
DURATION_METRICS = (
    "revenue",
    "free_cash_flow",
    "fcf_margin",
    "revenue_growth",
    "operating_cash_flow",
    "capital_expenditure",
)
# Balance-sheet style metrics: point-in-time instants.
INSTANT_METRICS = (
    "net_debt",
    "shares_diluted",
    "cash_and_equivalents",
    "total_debt",
    # Puente EV -> equity: derechos de minoritarios y preferentes. Opcionales
    # (no bloquean el DCF): la mayoría de emisores no los tiene.
    "minority_interest",
    "preferred_stock",
)
# The DCF equity bridge is EV - net_debt. A missing net_debt is NOT zero debt:
# it is an unknown that must block the valuation instead of inventing equity.
# Presence + finiteness is the requirement; positivity is NOT, because a
# negative net_debt is net cash and a perfectly valid (and bullish) input.
REQUIRED_FOR_DCF = ("revenue", "shares_diluted", "net_debt")
# Metrics used as a denominator or a scale, which must be strictly positive.
POSITIVE_REQUIRED_FOR_DCF = ("revenue", "shares_diluted")
# Inputs que se cruzan SIEMPRE entre fuentes (owner 3-nov-2026).
CROSS_CHECKED_INPUTS = ("total_debt", "cash_and_equivalents", "net_debt", "shares_diluted", "free_cash_flow")
# Un cero de una sola fuente en estos no se acepta (posible hueco de mapeo).
ZERO_NEEDS_CONFIRMATION = ("total_debt", "shares_diluted")


@dataclass
class FinancialSnapshot:
    as_of_period: str | None = None
    fiscal_year: int | None = None
    fiscal_quarter: str | None = None
    period_type: str | None = None  # FY | Q | TTM
    income_statement: str | None = None
    balance_sheet: str | None = None
    shares_period: str | None = None
    facts: dict[str, FinancialFact] = field(default_factory=dict)
    missing_inputs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Metricas con hechos PERSISTIDOS pero excluidos del snapshot por
    # desalineacion de periodo con el ancla (p. ej. acciones FY2025 con ancla
    # revenue FY2023). No son entradas ausentes: pedirlas al usuario seria
    # falso. Se exponen aparte para que la tesis lo diga con fechas.
    excluded_present: list[dict] = field(default_factory=list)
    coherent: bool = False
    # metric -> ids of the persisted facts it was derived from (e.g. net_debt
    # = total_debt - cash_and_equivalents). Derived facts are not persisted.
    derived: dict[str, list[int]] = field(default_factory=dict)
    # Corte point-in-time por fecha de PUBLICACION (filed). None = sin corte
    # (valoracion actual). Con corte, solo entran hechos con filed <= corte;
    # los excluidos se cuentan para que el trace audite la cobertura real.
    filed_cutoff: str | None = None
    filed_excluded_future: int = 0
    filed_excluded_unknown: int = 0
    # metric -> factor de splits posteriores al hecho (acciones x factor). El
    # precio es de hoy (o del as_of); sin esto un 4:1 tras el cierre dejaba el
    # valor por accion x4 frente a un precio ya dividido entre 4.
    split_factors: dict[str, float] = field(default_factory=dict)
    # metric -> procedencia multi-fuente (bridge_sources) de las piezas del
    # puente que el camino estricto no encontro y se resolvieron cruzando
    # fuentes / cierres cercanos. Todo lo que hay aqui se muestra ETIQUETADO
    # (confirmado, una sola fuente no oficial, discrepancia) en la traza y
    # en la tesis; nunca como dato oficial del ancla.
    bridge_provenance: dict[str, dict] = field(default_factory=dict)
    # Cruce de fuentes de los inputs YA presentes (confirmado / discrepancia);
    # no son estimaciones: van a la traza, no a «inputs estimados».
    source_checks: dict[str, dict] = field(default_factory=dict)

    def value(self, metric: str) -> float | None:
        """Return a finite float, or ``None``.

        A stored ``NaN``/``inf`` (allowed by ``Numeric(24, 6)`` in Postgres) is
        treated as a missing input instead of poisoning the whole valuation:
        every downstream clamp in this package is transparent to NaN.
        """
        fact = self.facts.get(metric)
        if fact is None:
            return None
        value = float(fact.value)
        if not math.isfinite(value):
            return None
        return value * self.split_factors.get(metric, 1.0)

    def fact_ids(self) -> dict[str, int | None]:
        return {metric: fact.id for metric, fact in self.facts.items()}

    def periods(self) -> dict[str, str | None]:
        return {metric: fact.period for metric, fact in self.facts.items()}


def _period_type(period: str | None, fiscal_quarter: str | None) -> str:
    text = (period or "").upper()
    if "TTM" in text:
        return "TTM"
    if fiscal_quarter and fiscal_quarter.upper() not in {"FY", "ANNUAL", ""}:
        return "Q"
    if text.startswith("Q") or "Q1" in text or "Q2" in text or "Q3" in text or "Q4" in text:
        return "Q"
    return "FY"


_PRIMARY_SOURCE_TYPES = ("SEC", "ESEF", "CNMV")


def _facts_for_metric(db: Session, company_id: int, metric: str) -> list[FinancialFact]:
    return [fact for fact in db.scalars(
            select(FinancialFact).options(selectinload(FinancialFact.source))
            .where(FinancialFact.company_id == company_id, FinancialFact.metric == metric)
            .order_by(
                FinancialFact.fiscal_year.desc().nullslast(),
                # Mismo ejercicio: la presentacion oficial antes que un
                # agregador (Yahoo/FMP) aunque este se haya traido despues;
                # el cruce de fuentes compara las demas (owner 3-nov-2026).
                case((FinancialFact.source_type.in_(_PRIMARY_SOURCE_TYPES), 0), else_=1),
                desc(FinancialFact.created_at),
            )
        ).all() if not fact_quarantine_reason(fact) and eligible_fact(fact)]


def _available_at(
    facts: list[FinancialFact], as_of: date | None
) -> tuple[list[FinancialFact], int, int]:
    """Filtra hechos por disponibilidad real en el corte (eje ``filed``).

    Un hecho con ``filed`` posterior al corte es informacion del futuro en un
    replay (V1). Un hecho con ``filed`` NULL no puede demostrar cuándo fue
    conocible (filas no-SEC, anteriores a la migracion 0082 o derivadas sin
    entradas fechadas): con corte explicito se excluye y se cuenta, en vez de
    adivinar disponibilidad. Sin corte (``as_of=None``) todo pasa: la
    valoracion actual no cambia de comportamiento.
    """
    if as_of is None:
        return facts, 0, 0
    available: list[FinancialFact] = []
    future = 0
    unknown = 0
    for fact in facts:
        if fact.filed is None:
            unknown += 1
        elif fact.filed <= as_of:
            available.append(fact)
        else:
            future += 1
    return available, future, unknown


def _filed_cutoff_warning(as_of: date, future: int, unknown: int) -> str:
    parts = []
    if future:
        parts.append(f"{future} publicados despues del corte")
    if unknown:
        parts.append(f"{unknown} sin fecha de publicacion demostrable")
    return (
        "Corte point-in-time "
        f"{as_of.isoformat()}: {' y '.join(parts)}; "
        "excluidos del snapshot (no eran conocibles en la fecha)."
    )


def _missing_without_revenue_anchor(
    db: Session,
    company_id: int,
    facts_provider=None,
) -> tuple[list[str], list[str]]:
    """Entradas genuinamente ausentes cuando falta el ancla de revenue.

    QA datos (ASML, 2026-10-18): el corte temprano declaraba ausentes
    shares_diluted y FCF sin comprobarlo, y shares_diluted estaba guardado
    (la ficha mostraba «Acciones diluidas (media) 2025-12-31:FY 388,9 M
    SEC»). Sin revenue no hay snapshot coherente, pero una entrada
    presente no esta «ausente»: solo se reportan las que faltan de verdad
    y las presentes quedan explicadas en warnings.
    """
    provider = facts_provider or (
        lambda metric: _facts_for_metric(db, company_id, metric)
    )
    missing = ["revenue"]
    warnings: list[str] = []
    if provider("shares_diluted"):
        warnings.append(
            "Hay acciones diluidas guardadas, pero no se usan porque falta "
            "el revenue."
        )
    else:
        missing.append("shares_diluted")
    has_fcf = bool(provider("free_cash_flow"))
    has_margin = bool(provider("fcf_margin"))
    if has_fcf or has_margin:
        warnings.append(
            "Hay flujo de caja libre guardado, pero no se usa porque falta "
            "el revenue."
        )
    else:
        missing.append("free_cash_flow_or_fcf_margin")
    return missing, warnings


def _same_duration_period(anchor: FinancialFact, candidate: FinancialFact) -> bool:
    # A TTM anchor is not interchangeable with an FY fact (nor with a quarter):
    # both are "duration" facts but they cover different windows, so pairing
    # them silently mixes a 12-month numerator with a 15-month denominator.
    anchor_kind = _period_type(anchor.period, anchor.fiscal_quarter)
    candidate_kind = _period_type(candidate.period, candidate.fiscal_quarter)
    if anchor_kind != candidate_kind:
        return False
    if anchor.fiscal_year is not None and candidate.fiscal_year is not None:
        if candidate.fiscal_year != anchor.fiscal_year:
            return False
        anchor_q = (anchor.fiscal_quarter or "FY").upper()
        cand_q = (candidate.fiscal_quarter or "FY").upper()
        if anchor_q in {"FY", "ANNUAL"} and cand_q in {"FY", "ANNUAL", ""}:
            return True
        return anchor_q == cand_q
    return (anchor.period or "").upper() == (candidate.period or "").upper()


def _compatible_instant(anchor: FinancialFact, candidate: FinancialFact) -> bool:
    """Balance-sheet / shares may be same FY or a later instant in the same year."""
    if anchor.fiscal_year is None or candidate.fiscal_year is None:
        return (anchor.period or "").upper() == (candidate.period or "").upper()
    if candidate.fiscal_year < anchor.fiscal_year:
        return False
    if candidate.fiscal_year > anchor.fiscal_year + 1:
        return False
    return True


_PERIOD_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _same_balance_instant(a: FinancialFact, b: FinancialFact) -> bool:
    """Mismo cierre de balance aunque la fuente lo etiquete distinto.

    «2025-12-31:FY» y «2025-12-31» son el mismo instante; «FY2025» frente a una
    fecha sólo coincide si el año fiscal es el mismo y ambos son anuales. Nunca
    se empareja un trimestre con otro cierre ni se adivina una fecha.
    """
    pa, pb = (a.period or "").upper(), (b.period or "").upper()
    da, db_ = _PERIOD_DATE.match(pa), _PERIOD_DATE.match(pb)
    if da and db_:
        return da.group(1) == db_.group(1)
    if not da and not db_:
        return pa == pb
    if a.fiscal_year is None or b.fiscal_year is None or a.fiscal_year != b.fiscal_year:
        return False
    annual = {"FY", "ANNUAL", ""}
    return (a.fiscal_quarter or "FY").upper() in annual and (b.fiscal_quarter or "FY").upper() in annual


def _pick_matching(
    candidates: list[FinancialFact],
    anchor: FinancialFact,
    *,
    instant: bool,
) -> FinancialFact | None:
    matcher = _compatible_instant if instant else _same_duration_period
    for fact in candidates:
        if matcher(anchor, fact):
            return fact
    return None


class FinancialSnapshotBuilder:
    """Assemble a coherent valuation snapshot from FinancialFact rows."""

    @staticmethod
    def _derive_net_debt(
        snapshot: FinancialSnapshot,
        anchor: FinancialFact,
        debt_candidates: list[FinancialFact],
        cash_candidates: list[FinancialFact],
    ) -> None:
        """net_debt = total_debt - cash_and_equivalents when both are reported.

        Only when no net_debt fact exists, and only when both inputs are
        persisted facts of the SAME balance-sheet instant (compatible with the
        anchor) and currency. Among the candidates the newest common instant
        wins, so a newer debt without a matching cash never blocks an older
        instant where both exist. The result is a transient ``derivado`` fact
        (never added to the session) and the ids of its two sources are exposed
        in ``snapshot.derived``.
        """
        if "net_debt" in snapshot.facts:
            return
        debt = cash = None
        for d_fact in debt_candidates:
            if not _compatible_instant(anchor, d_fact):
                continue
            c_fact = next(
                (
                    c
                    for c in cash_candidates
                    if _compatible_instant(anchor, c)
                    and _same_balance_instant(d_fact, c)
                    and (c.unit or "") == (d_fact.unit or "")
                ),
                None,
            )
            if c_fact is not None:
                debt, cash = d_fact, c_fact
                break
        if debt is None or cash is None:
            return
        try:
            d, c = float(debt.value), float(cash.value)
        except (TypeError, ValueError):
            return
        if not (math.isfinite(d) and math.isfinite(c)):
            return
        # Both inputs must come from the same source document; otherwise the
        # derived fact has no single source and the audit keeps it unsupported.
        shared_source = debt.source_id if debt.source_id == cash.source_id else None
        derived = FinancialFact(
            company_id=debt.company_id,
            source_id=shared_source,
            metric="net_debt",
            value=Decimal(str(d - c)),
            period=debt.period,
            fiscal_year=debt.fiscal_year,
            fiscal_quarter=debt.fiscal_quarter,
            unit=debt.unit,
            source_type="DERIVED",
            is_reported=False,
            is_adjusted=False,
            # Column defaults only apply on INSERT; this fact is transient, so
            # every attribute downstream code reads must be set explicitly.
            confidence=min(
                Decimal(str(debt.confidence if debt.confidence is not None else "0.8")),
                Decimal(str(cash.confidence if cash.confidence is not None else "0.8")),
            ),
        )
        snapshot.facts["net_debt"] = derived
        snapshot.balance_sheet = debt.period
        snapshot.derived["net_debt"] = [i for i in (debt.id, cash.id) if i is not None]

    @staticmethod
    def _derive_free_cash_flow(snapshot: FinancialSnapshot) -> None:
        """free_cash_flow = operating_cash_flow - |capital_expenditure| (+ margen).

        Solo si no hay FCF ni margen FCF y ambos componentes son hechos
        persistidos del MISMO periodo del ancla (ya filtrados por periodo en
        ``build``). Es un hecho transitorio ``DERIVED``: nunca se guarda ni se
        presenta como reportado. Sin uno de los dos componentes no se deriva.
        """
        if "free_cash_flow" in snapshot.facts or "fcf_margin" in snapshot.facts:
            return
        ocf = snapshot.facts.get("operating_cash_flow")
        capex = snapshot.facts.get("capital_expenditure")
        if ocf is None or capex is None:
            return
        if (ocf.unit or "") != (capex.unit or ""):
            return
        try:
            o, c = float(ocf.value), abs(float(capex.value))
        except (TypeError, ValueError):
            return
        if not (math.isfinite(o) and math.isfinite(c)):
            return
        confidence = min(
            Decimal(str(ocf.confidence if ocf.confidence is not None else "0.8")),
            Decimal(str(capex.confidence if capex.confidence is not None else "0.8")),
        )

        def _fact(metric: str, value: Decimal, unit: str | None) -> FinancialFact:
            return FinancialFact(
                company_id=ocf.company_id,
                source_id=ocf.source_id if ocf.source_id == capex.source_id else None,
                metric=metric,
                value=value,
                period=ocf.period,
                fiscal_year=ocf.fiscal_year,
                fiscal_quarter=ocf.fiscal_quarter,
                unit=unit,
                source_type="DERIVED",
                is_reported=False,
                is_adjusted=False,
                confidence=confidence,
            )

        sources = [i for i in (ocf.id, capex.id) if i is not None]
        snapshot.facts["free_cash_flow"] = _fact(
            "free_cash_flow", Decimal(str(o - c)), ocf.unit
        )
        snapshot.derived["free_cash_flow"] = sources
        revenue = snapshot.facts.get("revenue")
        if revenue is not None and (revenue.unit or "") == (ocf.unit or ""):
            try:
                r = float(revenue.value)
            except (TypeError, ValueError):
                return
            if math.isfinite(r) and r > 0:
                snapshot.facts["fcf_margin"] = _fact(
                    "fcf_margin", Decimal(str((o - c) / r)), "decimal"
                )
                snapshot.derived["fcf_margin"] = sources + [
                    i for i in (revenue.id,) if i is not None
                ]

    @staticmethod
    def _cross_check_sources(
        snapshot: FinancialSnapshot,
        anchor: FinancialFact,
        facts_for,
        *,
        as_of: date | None,
        drop_unconfirmed_zero: bool,
    ) -> None:
        """Cruza SIEMPRE con todas las fuentes guardadas los inputs ya elegidos.

        Owner 3-nov-2026: «siempre miramos todas las fuentes», no solo cuando
        falta un dato. Para deuda, caja, deuda neta, acciones y FCF elegidos por
        el camino estricto se comparan los cierres del MISMO periodo de cada
        fuente (oficial, FMP, Yahoo...). Un cero que ninguna otra fuente
        confirma se retira (puede ser un hueco de mapeo) para que el cruce de
        huecos lo resuelva; una discrepancia queda en ``source_checks`` y en
        los avisos, y manda la presentacion oficial mas reciente (la elegida).
        """
        from app.valuation import bridge_sources as bs

        for metric in CROSS_CHECKED_INPUTS:
            fact = snapshot.facts.get(metric)
            if fact is None or metric in snapshot.source_checks or metric in snapshot.bridge_provenance:
                continue
            period_end = bs._period_end(fact)
            if period_end is None:
                continue
            same_close = [
                f for f in facts_for(metric)
                if bs._period_end(f) == period_end and (as_of is None or period_end <= as_of)
            ]
            others = [c for c in bs.newest_per_source(same_close) if c.source != bs._source_key(fact)]
            try:
                chosen_value = float(fact.value)
            except (TypeError, ValueError):
                continue
            chosen = bs.Candidate(bs._source_key(fact), chosen_value, fact.period, period_end, fact)
            if not others:
                if drop_unconfirmed_zero and abs(chosen_value) < 1e-9 and metric in ZERO_NEEDS_CONFIRMATION:
                    snapshot.facts.pop(metric, None)
                    snapshot.warnings.append(
                        f"{metric} = 0 de una sola fuente ({bs.source_label(chosen.source)}) no se acepta: "
                        "se busca en otras fuentes."
                    )
                continue
            resolved = bs.resolve(metric, [chosen, *others])
            if resolved is None:
                if drop_unconfirmed_zero and metric in ZERO_NEEDS_CONFIRMATION:
                    snapshot.facts.pop(metric, None)
                continue
            snapshot.source_checks[metric] = {**resolved.as_dict(), "estimated": False}
            if resolved.status == "discrepancy":
                snapshot.warnings.append(f"{metric}: {resolved.note}.")

    @staticmethod
    def _resolve_bridge_gaps(
        db: Session,
        company: Company,
        snapshot: FinancialSnapshot,
        anchor: FinancialFact,
        facts_for,
        *,
        as_of: date | None,
        price_as_of: date | None,
    ) -> None:
        """Deuda neta / acciones que el camino estricto no encontro.

        Cruza TODAS las fuentes guardadas (oficial, FMP, Yahoo) con la regla
        de :mod:`app.valuation.bridge_sources` en una ventana de cierres
        cercanos al ancla. Lo resuelto entra al snapshot como hecho transitorio
        (no se persiste) y su procedencia en ``bridge_provenance``.
        """
        from app.valuation import bridge_sources as bs

        anchor_end = bs._period_end(anchor) or date.today()
        not_before = anchor_end - timedelta(days=bs.MAX_STALENESS_DAYS)
        not_after = anchor_end + timedelta(days=366)
        if as_of is not None:
            not_after = min(not_after, as_of)

        def _transient(metric: str, cand: bs.Candidate, value: float, unit: str | None) -> FinancialFact:
            base = cand.fact
            return FinancialFact(
                company_id=company.id,
                metric=metric,
                value=Decimal(str(value)),
                unit=unit,
                period=cand.period,
                fiscal_year=getattr(base, "fiscal_year", None),
                fiscal_quarter=getattr(base, "fiscal_quarter", None),
                source_type=cand.source,
                is_reported=False,
            )

        if "net_debt" not in snapshot.facts:
            direct = bs.newest_per_source(facts_for("net_debt"), not_after=not_after, not_before=not_before)
            debts = bs.newest_per_source(facts_for("total_debt"), not_after=not_after, not_before=not_before)
            cash_all = facts_for("cash_and_equivalents")
            by_source = {c.source: c for c in direct}
            derived_ids: dict[str, list[int]] = {}
            for debt in debts:
                if debt.source in by_source:
                    continue
                # Caja de la MISMA fuente y del MISMO cierre que la deuda; si esa
                # fuente no la trae, la oficial de ese cierre (la caja es la pieza
                # que el oficial casi siempre publica).
                cash = next(
                    (
                        c for c in bs.newest_per_source(
                            [f for f in cash_all if bs._period_end(f) == debt.period_end
                             and (f.unit or "") == (debt.fact.unit or "")]
                        )
                        if c.source == debt.source
                    ),
                    None,
                ) or next(
                    iter(
                        bs.newest_per_source(
                            [f for f in cash_all if bs._period_end(f) == debt.period_end
                             and (f.unit or "") == (debt.fact.unit or "")]
                        )
                    ),
                    None,
                )
                if cash is None:
                    continue
                fact = _transient("net_debt", debt, debt.value - cash.value, getattr(debt.fact, "unit", None))
                by_source[debt.source] = bs.Candidate(
                    debt.source, debt.value - cash.value, debt.period, debt.period_end, fact
                )
                derived_ids[debt.source] = [
                    i for i in (getattr(debt.fact, "id", None), getattr(cash.fact, "id", None)) if i
                ]
            candidates = sorted(by_source.values(), key=lambda c: (c.period_end or date.min), reverse=True)
            scale = max((abs(d.value) for d in debts), default=None)
            resolved = bs.resolve("net_debt", candidates, scale=scale)
            if resolved is not None:
                snapshot.facts["net_debt"] = resolved.chosen.fact
                snapshot.balance_sheet = resolved.chosen.period
                if resolved.chosen.source in derived_ids:
                    snapshot.derived["net_debt"] = derived_ids[resolved.chosen.source]
                snapshot.bridge_provenance["net_debt"] = {
                    **resolved.as_dict(),
                    "method": "deuda total − caja" if resolved.chosen.source in derived_ids else "deuda neta declarada",
                    "estimated": True,
                }
                snapshot.warnings.append(f"net_debt resuelta por cruce de fuentes: {resolved.note}.")

        if "shares_diluted" not in snapshot.facts:
            diluted = bs.newest_per_source(facts_for("shares_diluted"), not_after=not_after, not_before=not_before)
            outstanding = bs.newest_per_source(
                facts_for("shares_outstanding"), not_after=not_after, not_before=not_before
            )
            sources = {c.source for c in diluted}
            # Acciones en circulacion como candidata de la fuente que no da
            # diluidas: aproximacion etiquetada (sin la dilucion de opciones).
            approx = [c for c in outstanding if c.source not in sources]
            candidates = sorted([*diluted, *approx], key=lambda c: (c.period_end or date.min), reverse=True)
            resolved = bs.resolve("shares_diluted", candidates)
            if resolved is not None and resolved.chosen.value > 0:
                chosen_fact = resolved.chosen.fact
                snapshot.facts["shares_diluted"] = chosen_fact
                snapshot.shares_period = resolved.chosen.period
                factor = float(
                    split_factor_for_fact(
                        db,
                        company.id,
                        period=resolved.chosen.period,
                        filed=getattr(chosen_fact, "filed", None),
                        cutoff=price_as_of or as_of or date.today(),
                    )
                )
                if factor != 1.0:
                    snapshot.split_factors["shares_diluted"] = factor
                snapshot.bridge_provenance["shares_diluted"] = {
                    **resolved.as_dict(),
                    "method": (
                        "acciones en circulación (sin dilución)"
                        if resolved.chosen in approx
                        else "acciones diluidas declaradas"
                    ),
                    "estimated": True,
                }
                snapshot.warnings.append(f"shares_diluted resueltas por cruce de fuentes: {resolved.note}.")

    def build(
        self,
        db: Session,
        company: Company,
        *,
        as_of: date | None = None,
        price_as_of: date | None = None,
    ) -> FinancialSnapshot:
        excluded_future = 0
        excluded_unknown = 0
        cache: dict[str, list[FinancialFact]] = {}

        def facts_for(metric: str) -> list[FinancialFact]:
            nonlocal excluded_future, excluded_unknown
            if metric not in cache:
                available, future, unknown = _available_at(
                    _facts_for_metric(db, company.id, metric), as_of
                )
                cache[metric] = available
                excluded_future += future
                excluded_unknown += unknown
            return cache[metric]

        revenue_candidates = facts_for("revenue")
        if not revenue_candidates:
            missing, warnings = _missing_without_revenue_anchor(
                db, company.id, facts_provider=facts_for
            )
            if as_of is not None and (excluded_future or excluded_unknown):
                warnings.append(_filed_cutoff_warning(as_of, excluded_future, excluded_unknown))
            return FinancialSnapshot(
                missing_inputs=missing,
                coherent=False,
                warnings=warnings,
                filed_cutoff=as_of.isoformat() if as_of is not None else None,
                filed_excluded_future=excluded_future,
                filed_excluded_unknown=excluded_unknown,
            )

        anchor = revenue_candidates[0]
        snapshot = FinancialSnapshot(
            as_of_period=anchor.period,
            fiscal_year=anchor.fiscal_year,
            fiscal_quarter=anchor.fiscal_quarter,
            period_type=_period_type(anchor.period, anchor.fiscal_quarter),
            income_statement=anchor.period,
            facts={"revenue": anchor},
        )

        for metric in DURATION_METRICS:
            if metric == "revenue":
                continue
            match = _pick_matching(facts_for(metric), anchor, instant=False)
            if match:
                snapshot.facts[metric] = match
            else:
                latest = facts_for(metric)
                if latest:
                    snapshot.warnings.append(
                        f"{metric} latest period {latest[0].period} does not match "
                        f"anchor {anchor.period}; excluded from snapshot."
                    )
                    snapshot.excluded_present.append(
                        {
                            "metric": metric,
                            "available_period": latest[0].period,
                            "anchor_period": anchor.period,
                            "reason": "period_mismatch",
                        }
                    )

        for metric in INSTANT_METRICS:
            match = _pick_matching(facts_for(metric), anchor, instant=True)
            if match:
                snapshot.facts[metric] = match
                if metric == "net_debt":
                    snapshot.balance_sheet = match.period
                    if (
                        anchor.fiscal_year is not None
                        and match.fiscal_year is not None
                        and match.fiscal_year != anchor.fiscal_year
                    ):
                        # Cross-period balance sheet: expose it instead of
                        # letting a consumer read it as the anchor's own.
                        snapshot.warnings.append(
                            f"net_debt period {match.period} is a different fiscal year "
                            f"than the income statement anchor {anchor.period}."
                        )
                if metric == "shares_diluted":
                    snapshot.shares_period = match.period
                    factor = float(
                        split_factor_for_fact(
                            db,
                            company.id,
                            period=match.period,
                            filed=match.filed,
                            # Fecha del PRECIO con el que se comparan: un
                            # cierre guardado antes del split esta en la base
                            # vieja y las acciones tienen que ir en la misma.
                            cutoff=price_as_of or as_of or date.today(),
                        )
                    )
                    if factor != 1.0:
                        snapshot.split_factors["shares_diluted"] = factor
                        snapshot.warnings.append(
                            f"shares_diluted {match.period} ajustadas por splits "
                            f"posteriores al cierre (x{factor:g}) para compararlas "
                            "con el precio actual."
                        )
            else:
                latest = facts_for(metric)
                if latest:
                    snapshot.warnings.append(
                        f"{metric} latest period {latest[0].period} is incompatible "
                        f"with anchor {anchor.period}; excluded from snapshot."
                    )
                    snapshot.excluded_present.append(
                        {
                            "metric": metric,
                            "available_period": latest[0].period,
                            "anchor_period": anchor.period,
                            "reason": "period_mismatch",
                        }
                    )

        self._derive_net_debt(
            snapshot,
            anchor,
            facts_for("total_debt"),
            facts_for("cash_and_equivalents"),
        )
        self._derive_free_cash_flow(snapshot)
        self._cross_check_sources(snapshot, anchor, facts_for, as_of=as_of, drop_unconfirmed_zero=True)
        self._resolve_bridge_gaps(
            db, company, snapshot, anchor, facts_for, as_of=as_of, price_as_of=price_as_of
        )
        self._cross_check_sources(snapshot, anchor, facts_for, as_of=as_of, drop_unconfirmed_zero=False)

        missing: list[str] = []
        for metric in REQUIRED_FOR_DCF:
            fact = snapshot.facts.get(metric)
            if fact is None or not math.isfinite(float(fact.value)) or metric in POSITIVE_REQUIRED_FOR_DCF and float(fact.value) <= 0:
                # Un required excluido por periodo SIGUE bloqueando el DCF
                # (coherent=False): la coherencia interna no se negocia. La
                # distincion "presente pero excluido" vs "ausente" es solo
                # explicacion al usuario (excluded_present), nunca gating.
                missing.append(metric)

        has_margin = "fcf_margin" in snapshot.facts
        has_fcf = "free_cash_flow" in snapshot.facts
        if not has_margin and not has_fcf:
            missing.append("normalized_fcf_or_fcf_margin")

        # Presente pero NO utilizable (explicacion al usuario, nunca gating):
        # - revenue con hecho persistido (el ancla) cuyo valor no alimenta el
        #   modelo (p. ej. 0 reportado): no es un dato ausente, pedirlo seria
        #   falso.
        # - net_debt derivable solo de componentes excluidos por periodo: se
        #   explica como presente-excluido derivado, no como ausente.
        if "revenue" in missing and anchor is not None:
            try:
                anchor_value = float(anchor.value)
            except (TypeError, ValueError):
                anchor_value = float("nan")
            if not math.isfinite(anchor_value):
                detail = "ingresos reportados no finitos en el periodo ancla"
            elif anchor_value == 0:
                detail = "ingresos reportados 0 en el periodo ancla"
            else:
                detail = "ingresos reportados no positivos en el periodo ancla"
            snapshot.excluded_present.append(
                {
                    "metric": "revenue",
                    "available_period": anchor.period,
                    "anchor_period": anchor.period,
                    "reason": "present_not_usable",
                    "detail": detail,
                    "reported_value": anchor_value if math.isfinite(anchor_value) else None,
                }
            )
        if "net_debt" in missing:
            excluded_metrics = {
                str(item.get("metric")) for item in snapshot.excluded_present
            }
            if {"total_debt", "cash_and_equivalents"} <= excluded_metrics:
                periods = sorted(
                    str(item.get("available_period"))
                    for item in snapshot.excluded_present
                    if item.get("metric") in ("total_debt", "cash_and_equivalents")
                )
                snapshot.excluded_present.append(
                    {
                        "metric": "net_debt",
                        "available_period": periods[-1] if periods else None,
                        "anchor_period": anchor.period,
                        "reason": "components_excluded",
                        "detail": "se deriva de deuda total y efectivo presentes "
                        "fuera del periodo ancla",
                    }
                )

        if as_of is not None:
            snapshot.filed_cutoff = as_of.isoformat()
            snapshot.filed_excluded_future = excluded_future
            snapshot.filed_excluded_unknown = excluded_unknown
            if excluded_future or excluded_unknown:
                snapshot.warnings.append(
                    _filed_cutoff_warning(as_of, excluded_future, excluded_unknown)
                )
        snapshot.missing_inputs = missing
        snapshot.coherent = not missing
        return snapshot
