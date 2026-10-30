"""Proyeccion determinista de tesis a 5 ejercicios (PR A: sin LLM).

Todo numero sale de calculo sobre datos ya persistidos: facts anuales
oficiales (SEC/ESEF), asunciones de driver versionadas, ValuationAssumption e
InferredInput. Si falta un input critico la salida es N/D explicito: nunca un
0 ni un valor por defecto silencioso. El precio objetivo a 5 anos se apoya en
ValuationService (no se reimplementa el DCF) y se rotula INFERIDO por ser
proyeccion propia. La capa LLM (PR B) consume este contrato; aqui no se llama
a ningun modelo.

Dos invariantes de procedencia:

- OFICIAL exige URL + fecha verificables contra el documento persistido
  (politica de thesis_provenance). Un source_type "SEC" sin documento
  enlazado, o un documento sin url o sin fecha de publicacion, cae a
  INFERIDO con la fuente nombrada: nunca OFICIAL de prestado.
- Sin lookahead por fecha conocida, no solo por ejercicio: el cierre exacto
  del periodo ("2026-12-31:FY"), la fecha de publicacion del documento
  fuente, el created_at de cada version de asuncion/inferido y la fecha del
  precio se contrastan con as_of. Lo que es de despues del corte levanta
  LookaheadError.
"""

from __future__ import annotations

import hashlib
import math
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, desc, func, select, text
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import (
    Company,
    Document,
    DriverAssumptionVersion,
    FinancialFact,
    FundamentalDriver,
    ThesisProjectionYear,
    ValuationAssumption,
    ValuationModel,
    ValuationOutput,
)
from app.services.inferred_input_service import InferredInputService
from app.services.valuation_service import (
    ValuationService,
    _position_price,
    _position_price_as_of,
)
from app.valuation.engines.base import margin_of_safety
from app.valuation.point_in_time import (
    assert_fiscal_year_no_lookahead,
    assert_no_lookahead,
    assert_period_no_lookahead,
)

MODEL_TYPE = "thesis_5y"
MODEL_VERSION = "thesis-projection-v1"
HORIZON_YEARS = 5
SCENARIOS = ("bear", "base", "bull")

LABEL_OFICIAL = "OFICIAL"
LABEL_INFERIDO = "INFERIDO"
LABEL_ND = "N/D"
PUBLISHABLE_MIN_RATIO = 0.25
PUBLISHABLE_MAX_RATIO = 4.0

DISCLAIMER_ES = (
    "Proyección del modelo a 5 ejercicios basada en hipotesis propias "
    "(INFERIDO): no es un dato oficial ni una recomendación de inversión. "
    "Las decisiones de inversión son responsabilidad del usuario."
)

# Facts cuya fuente puede ser oficial SI se verifica contra el documento
# persistido (url + fecha). El source_type solo NO basta para la etiqueta.
OFFICIAL_FACT_SOURCES = frozenset({"SEC", "ESEF"})

# Dispersion de escenarios (politica del modelo): los mismos anchos que
# mechanical_dcf_scenarios para no inventar una segunda convencion.
GROWTH_SPREAD = 0.08
MARGIN_SPREAD = 0.06
MARGIN_CAP = 0.45

# Cuota diaria de recalculos persistidos por TENANT (POST). El GET es
# calculo puro y no consume cuota.
DAILY_RECALC_QUOTA = 10

GROWTH_KEY = "revenue_growth"
MARGIN_KEY = "fcf_margin"
ANNUAL_METRICS = ("revenue", "free_cash_flow", "net_income", "shares_diluted")


class ProjectionQuotaExceeded(Exception):
    def __init__(self, limit: int) -> None:
        super().__init__(f"cuota diaria de {limit} recalculos agotada")
        self.limit = limit


def _known_date(value: Any) -> date | None:
    """Fecha conocida de un created_at/published_at; None si no la hay."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


@dataclass(frozen=True)
class FactBase:
    """Ultimo dato anual conocido de una metrica, con su procedencia."""

    value: float | None
    fiscal_year: int | None
    label: str
    source: str | None
    source_url: str | None
    source_date: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "valor": self.value,
            "ejercicio": self.fiscal_year,
            "etiqueta": self.label,
            "fuente": self.source,
            "fuente_url": self.source_url,
            "fuente_fecha": self.source_date,
        }


@dataclass(frozen=True)
class RateAssumption:
    """Crecimiento o margen aplicable a un ejercicio/escenario."""

    value: float | None
    label: str
    base: str | None
    source_urls: tuple[str, ...] = ()
    source_url: str | None = None
    source_date: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "valor": self.value,
            "etiqueta": self.label,
            "base": self.base,
            "fuente_url": self.source_url,
            "fuente_fecha": self.source_date,
        }
        if self.source_urls:
            out["source_urls"] = list(self.source_urls)
        return out


@dataclass(frozen=True)
class VerifiedSource:
    """Documento fuente resuelto con verificacion de oficialidad."""

    url: str | None
    fecha: str | None
    title: str | None
    verified_official: bool


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


class ThesisProjectionService:
    """Proyeccion anual bear/base/bull a ``HORIZON_YEARS`` ejercicios."""

    # -- procedencia verificada ---------------------------------------------

    def _verified_source(
        self,
        db: Session,
        *,
        source_type: str | None,
        source_id: int | None,
        as_of: date,
        label: str,
    ) -> VerifiedSource:
        """Resuelve el documento fuente y decide si la oficialidad se verifica.

        OFICIAL solo cuando el source_type es de filing oficial Y el documento
        persistido tiene url y fecha de publicacion (la politica de
        thesis_provenance). Sin documento, sin url o sin fecha: no verificado
        (fail-closed a INFERIDO en el llamante). Una fecha de publicacion
        posterior al corte es lookahead, no un detalle estetico.
        """
        doc = db.get(Document, source_id) if source_id else None
        if doc is None:
            return VerifiedSource(None, None, None, False)
        published = _known_date(doc.published_at)
        assert_no_lookahead(
            as_of=as_of,
            data_date=published,
            label=f"documento fuente de {label}",
        )
        verified = (
            (source_type or "") in OFFICIAL_FACT_SOURCES
            and bool(doc.source_url)
            and published is not None
        )
        return VerifiedSource(
            doc.source_url,
            published.isoformat() if published else None,
            doc.title,
            verified,
        )

    # -- facts anuales ------------------------------------------------------

    def _annual_facts(
        self, db: Session, company: Company, as_of: date
    ) -> dict[str, dict[int, FinancialFact]]:
        """Ultimo fact anual por metrica y ejercicio, sin lookahead.

        El guard se aplica al PERIODO persistido (``assert_period_no_lookahead``
        entiende el cierre exacto "2026-12-31:FY", no solo el ano) y al
        fiscal_year como respaldo: un FY2026 que cierra en diciembre de 2026
        no es conocido en octubre de 2026 aunque el ano coincida.
        """
        rows = db.scalars(
            select(FinancialFact)
            .where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric.in_(ANNUAL_METRICS),
                FinancialFact.fiscal_year.is_not(None),
            )
            .order_by(FinancialFact.fiscal_year, desc(FinancialFact.id))
        ).all()
        out: dict[str, dict[int, FinancialFact]] = {}
        for row in rows:
            assert_period_no_lookahead(
                as_of=as_of,
                period=row.period,
                label=f"FinancialFact {company.ticker} {row.metric}",
            )
            assert_fiscal_year_no_lookahead(
                as_of=as_of,
                fiscal_year=row.fiscal_year,
                label=f"FinancialFact {company.ticker} {row.metric}",
            )
            if (row.fiscal_quarter or "").upper().startswith("Q"):
                continue
            # CADA fact que entra en la proyeccion (el ancla mas reciente y
            # los extremos del CAGR por igual) exige fuente no futura: un
            # restatement publicado despues del corte es lookahead aunque
            # cuelgue de un ejercicio viejo.
            if row.source_id:
                doc = db.get(Document, row.source_id)
                if doc is not None:
                    assert_no_lookahead(
                        as_of=as_of,
                        data_date=_known_date(doc.published_at),
                        label=(
                            f"documento fuente de FinancialFact {company.ticker} "
                            f"{row.metric} FY{row.fiscal_year}"
                        ),
                    )
            # Ordenado por id descendente: el primero por ejercicio es el mas
            # reciente; setdefault conserva ese y descarta restatements viejos.
            out.setdefault(row.metric, {}).setdefault(row.fiscal_year, row)  # type: ignore[arg-type]
        return out

    def _fact_base(
        self,
        db: Session,
        facts: dict[str, dict[int, FinancialFact]],
        metric: str,
        as_of: date,
    ) -> FactBase:
        by_year = facts.get(metric) or {}
        if not by_year:
            return FactBase(None, None, LABEL_ND, None, None, None)
        year = max(by_year)
        fact = by_year[year]
        verified = self._verified_source(
            db,
            source_type=fact.source_type,
            source_id=fact.source_id,
            as_of=as_of,
            label=f"{company_label(metric)} FY{year}",
        )
        detalle = fact.source_type or "desconocida"
        if verified.title:
            detalle = f"{detalle} ({verified.title})"
        if verified.verified_official:
            return FactBase(
                _num(fact.value),
                year,
                LABEL_OFICIAL,
                f"{detalle} FY{year}",
                verified.url,
                verified.fecha,
            )
        # Fail-closed: un source_type oficial sin documento verificable no
        # hereda la etiqueta OFICIAL; se nombra la fuente y la carencia.
        nota = (
            " (sin documento con url y fecha verificables)"
            if (fact.source_type or "") in OFFICIAL_FACT_SOURCES
            else ""
        )
        return FactBase(
            _num(fact.value),
            year,
            LABEL_INFERIDO,
            f"{detalle} FY{year}{nota}",
            verified.url,
            verified.fecha,
        )

    # -- asunciones ----------------------------------------------------------

    def _driver_overrides(
        self, db: Session, company: Company, as_of: date
    ) -> dict[tuple[str, int, str], dict[str, Any]]:
        """Ultima version por (driver_key, ejercicio, escenario), sin lookahead."""
        rows = db.execute(
            select(DriverAssumptionVersion, FundamentalDriver.driver_key)
            .join(FundamentalDriver)
            .where(
                FundamentalDriver.company_id == company.id,
                FundamentalDriver.driver_key.in_((GROWTH_KEY, MARGIN_KEY)),
            )
            .order_by(DriverAssumptionVersion.id)
        ).all()
        out: dict[tuple[str, int, str], dict[str, Any]] = {}
        for version, driver_key in rows:
            assert_no_lookahead(
                as_of=as_of,
                data_date=_known_date(version.created_at),
                label=f"asunción de driver {company.ticker} {driver_key}",
            )
            out[(driver_key, version.fiscal_year, version.scenario)] = {
                "value": _num(version.value),
                "source": version.source,
                "user_override": version.user_override,
            }
        return out

    def _valuation_assumptions(
        self, db: Session, company: Company, as_of: date
    ) -> dict[tuple[str, str, int], ValuationAssumption]:
        rows = db.scalars(
            select(ValuationAssumption)
            .join(
                ValuationModel,
                ValuationAssumption.valuation_model_id == ValuationModel.id,
            )
            .where(
                ValuationModel.company_id == company.id,
                ValuationAssumption.name.in_((GROWTH_KEY, MARGIN_KEY)),
                ValuationAssumption.year.is_not(None),
            )
            .order_by(ValuationAssumption.id)
        ).all()
        out: dict[tuple[str, str, int], ValuationAssumption] = {}
        for row in rows:
            assert_no_lookahead(
                as_of=as_of,
                data_date=_known_date(row.created_at),
                label=f"asunción de valoración {company.ticker} {row.name}",
            )
            out[(row.name, row.scenario, row.year)] = row  # type: ignore[index]
        return out

    def _stored_assumption_rate(
        self,
        db: Session,
        company: Company,
        stored: ValuationAssumption,
        as_of: date,
    ) -> RateAssumption:
        """Asuncion de valoracion persistida, con la misma regla de oficialidad."""
        verified = self._verified_source(
            db,
            source_type=stored.source_type,
            source_id=stored.source_id,
            as_of=as_of,
            label=f"asunción {company.ticker} {stored.name}",
        )
        # La url y la fecha verificadas viajan al contrato: afirmar la
        # oficialidad sin exponer su procedencia la haria inspeccionable.
        if verified.verified_official:
            return RateAssumption(
                _num(stored.value),
                LABEL_OFICIAL,
                f"asunción de valoración persistida (tipo {stored.source_type}, "
                f"documento verificado con url y fecha)",
                source_url=verified.url,
                source_date=verified.fecha,
            )
        return RateAssumption(
            _num(stored.value),
            LABEL_INFERIDO,
            f"asunción de valoración persistida (tipo {stored.source_type}, "
            f"sin documento con url y fecha verificables)",
            source_url=verified.url,
            source_date=verified.fecha,
        )

    @staticmethod
    def _revenue_cagr(by_year: dict[int, FinancialFact]) -> RateAssumption:
        """CAGR de ingresos sobre la historia anual disponible (INFERIDO)."""
        points = sorted(
            (year, _num(fact.value))
            for year, fact in by_year.items()
            if _num(fact.value) is not None
        )
        if len(points) < 2:
            return RateAssumption(None, LABEL_ND, None)
        (first_year, first), (last_year, last) = points[0], points[-1]
        span = last_year - first_year
        # Anclas no positivas: un CAGR con extremo <= 0 no esta definido en
        # reales (base negativa -> complejo) y no se arrastra a la proyeccion
        # como excepcion: N/D explicito, como cualquier input ausente.
        if span < 1 or first is None or last is None or first <= 0 or last <= 0:
            return RateAssumption(None, LABEL_ND, None)
        cagr = (last / first) ** (1 / span) - 1
        return RateAssumption(
            cagr,
            LABEL_INFERIDO,
            f"CAGR de ingresos FY{first_year}-FY{last_year} sobre facts anuales "
            f"({span} años); la historia no garantiza el futuro",
        )

    def _growth(
        self,
        db: Session,
        company: Company,
        scenario: str,
        year: int,
        *,
        as_of: date,
        drivers: dict[tuple[str, int, str], dict[str, Any]],
        val_assumptions: dict[tuple[str, str, int], ValuationAssumption],
        cagr: RateAssumption,
        burn: bool,
    ) -> RateAssumption:
        override = drivers.get((GROWTH_KEY, year, scenario))
        if override and override["value"] is not None:
            origen = "del usuario" if override["user_override"] else "del modelo"
            return RateAssumption(
                override["value"],
                LABEL_INFERIDO,
                f"asunción de driver '{GROWTH_KEY}' {origen} ({override['source']})",
            )
        stored = val_assumptions.get((GROWTH_KEY, scenario, year))
        if stored is not None:
            return self._stored_assumption_rate(db, company, stored, as_of)
        if cagr.value is None:
            return RateAssumption(None, LABEL_ND, None)
        if scenario == "base":
            return cagr
        if burn:
            # Con margen FCF negativo, mover el crecimiento invierte la
            # economia del escenario (crecer mas quema mas caja): la
            # dispersion honesta viene solo del margen, igual que en
            # mechanical_dcf_scenarios.
            return RateAssumption(
                cagr.value,
                LABEL_INFERIDO,
                f"{cagr.base}; sin dispersion por quema de caja (politica del modelo)",
            )
        delta = -GROWTH_SPREAD if scenario == "bear" else GROWTH_SPREAD
        return RateAssumption(
            cagr.value + delta,
            LABEL_INFERIDO,
            f"{cagr.base}; dispersion {delta:+.0%} sobre el base (politica del modelo)",
        )

    def _margin(
        self,
        db: Session,
        company: Company,
        scenario: str,
        year: int,
        *,
        as_of: date,
        drivers: dict[tuple[str, int, str], dict[str, Any]],
        val_assumptions: dict[tuple[str, str, int], ValuationAssumption],
        anchor: RateAssumption,
    ) -> RateAssumption:
        override = drivers.get((MARGIN_KEY, year, scenario))
        if override and override["value"] is not None:
            origen = "del usuario" if override["user_override"] else "del modelo"
            return RateAssumption(
                override["value"],
                LABEL_INFERIDO,
                f"asunción de driver '{MARGIN_KEY}' {origen} ({override['source']})",
            )
        stored = val_assumptions.get((MARGIN_KEY, scenario, year))
        if stored is not None:
            return self._stored_assumption_rate(db, company, stored, as_of)
        if anchor.value is None:
            return RateAssumption(None, LABEL_ND, None)
        if scenario == "base":
            return anchor
        delta = -MARGIN_SPREAD if scenario == "bear" else MARGIN_SPREAD
        value = anchor.value + delta
        if scenario == "bull":
            # Techo del 45% para márgenes normales, pero nunca por debajo del
            # base (misma regla que mechanical_dcf_scenarios tras #3008): con
            # un base del 50% el bull salía al 45%, peor que el base.
            value = min(value, max(MARGIN_CAP, anchor.value))
        return RateAssumption(
            value,
            LABEL_INFERIDO,
            f"{anchor.base}; dispersion {delta:+.0%} sobre el base (politica del modelo)",
        )

    def _margin_anchor(
        self,
        db: Session,
        company: Company,
        revenue: FactBase,
        fcf: FactBase,
        as_of: date,
    ) -> RateAssumption:
        """Margen FCF base: InferredInput validado o derivado de facts."""
        inferred = InferredInputService().latest_valid(db, company.id, MARGIN_KEY)
        if inferred is not None:
            assert_no_lookahead(
                as_of=as_of,
                data_date=_known_date(inferred.created_at),
                label=f"input inferido {company.ticker} {MARGIN_KEY}",
            )
            return RateAssumption(
                _num(inferred.value),
                LABEL_INFERIDO,
                f"input inferido documentado: {inferred.base}",
                tuple(inferred.source_urls or ()),
            )
        if (
            revenue.value is not None
            and fcf.value is not None
            and revenue.value != 0
            and revenue.fiscal_year == fcf.fiscal_year
        ):
            return RateAssumption(
                fcf.value / revenue.value,
                LABEL_INFERIDO,
                f"margen FCF derivado de facts FY{revenue.fiscal_year} "
                f"(FCF / ingresos del mismo ejercicio)",
            )
        return RateAssumption(None, LABEL_ND, None)

    @staticmethod
    def _net_margin(revenue: FactBase, net_income: FactBase) -> RateAssumption:
        if (
            revenue.value is not None
            and net_income.value is not None
            and revenue.value != 0
            and revenue.fiscal_year == net_income.fiscal_year
        ):
            return RateAssumption(
                net_income.value / revenue.value,
                LABEL_INFERIDO,
                f"margen neto derivado de facts FY{revenue.fiscal_year} "
                f"(resultado neto / ingresos del mismo ejercicio)",
            )
        return RateAssumption(None, LABEL_ND, None)

    # -- precio objetivo ------------------------------------------------------

    def _current_price(
        self, db: Session, company: Company, as_of: date
    ) -> tuple[float | None, str | None]:
        price = _position_price(db, company.id)
        price_date = _position_price_as_of(db, company.id)
        if price_date:
            assert_no_lookahead(
                as_of=as_of,
                data_date=date.fromisoformat(price_date),
                label=f"precio {company.ticker}",
            )
        return price, price_date

    def _scenario_targets(
        self,
        db: Session,
        company: Company,
        as_of: date,
        anchor_kind: str | None,
        anchor_base_ps: float | None,
        projected_ps: dict[str, float | None],
        price: float | None,
        price_date: str | None,
    ) -> dict[str, dict[str, Any]]:
        """Precio objetivo a 5 anos por escenario.

        No reimplementa el DCF: toma el valor por accion actual de
        ValuationService y lo convierte en un multiplo implicito sobre el
        fundamental por accion (FCF si es positivo, si no ingresos), aplicado
        al fundamental proyectado del ultimo ejercicio. Si falta cualquier
        pieza, N/D.
        """
        valuation: dict[str, Any] | None = None
        valuation_error: str | None = None
        try:
            valuation = ValuationService().value_company(db, company, as_of=as_of)
        except Exception as exc:  # noqa: BLE001 - un motor roto no rompe la proyeccion
            valuation_error = type(exc).__name__
        # Un valor del motor que el propio motor marca como no publicable
        # (blockers de fuente, estado blocked/insufficient_data) no puede
        # convertirse en objetivo final por reescalado: fail-closed a N/D
        # conservando las razones. La clave ausente tambien bloquea.
        publishable = bool(valuation and valuation.get("publishable"))
        blockers: list[Any] = []
        if valuation is not None:
            blockers = list(valuation.get("publication_blockers") or [])
        out: dict[str, dict[str, Any]] = {}
        for scenario in SCENARIOS:
            target: float | None = None
            base: str | None = None
            if valuation_error is not None:
                base = f"valoración no disponible ({valuation_error})"
            elif valuation is None or not publishable:
                razones = ", ".join(str(b) for b in blockers) or "sin razones declaradas"
                base = f"valoración del motor no publicable (bloqueos: {razones})"
            elif anchor_kind is None or anchor_base_ps in (None, 0):
                base = "sin ancla por acción (FCF o ingresos por acción no disponibles)"
            else:
                scenario_value = _num(valuation.get(f"{scenario}_value"))
                projected = projected_ps.get(scenario)
                if scenario_value is None or projected is None:
                    base = "sin valor del escenario o sin proyección del ancla"
                elif price is None or price <= 0 or price_date is None:
                    base = (
                        "sin precio fechado para acotar el multiplo (evita contar el "
                        "crecimiento dos veces)"
                    )
                else:
                    multiple = scenario_value / anchor_base_ps
                    # El valor actual del escenario ya descuenta su crecimiento; aplicar
                    # ese multiplo al ancla ya crecida lo cuenta dos veces. Tope: el
                    # multiplo de mercado actual (precio fechado / ancla por accion),
                    # sin expansion de multiplo. Convencion declarada, INFERIDO.
                    market_multiple = price / anchor_base_ps
                    capped = multiple > market_multiple
                    multiple = min(multiple, market_multiple)
                    target = projected * multiple
                    base = (
                        f"múltiplo implícito del modelo ({anchor_kind} por acción): "
                        f"valor/acción actual del escenario / {anchor_kind} por acción "
                        f"actual, aplicado al {anchor_kind} por acción proyectado"
                    )
                    if capped:
                        base += (
                            f"; acotado al multiplo de mercado actual ({market_multiple:.1f}x, "
                            f"precio del {price_date}), sin expansion de multiplo"
                        )
            # MOS solo contra precio FECHADO: un mark de Position sin fecha no
            # dice cuando era cierto, y comparar contra el seria silenciarlo.
            mos = (
                margin_of_safety(target, price)
                if target is not None and price is not None and price_date is not None
                else None
            )
            out[scenario] = {
                "valor": target,
                "etiqueta": LABEL_INFERIDO if target is not None else LABEL_ND,
                "base": base,
                "mos": mos,
                "bloqueos": blockers if not publishable else [],
            }
        return out

    # -- proyeccion -----------------------------------------------------------

    def project(
        self,
        db: Session,
        company: Company,
        *,
        as_of: date | None = None,
        horizon: int = HORIZON_YEARS,
    ) -> dict[str, Any]:
        as_of = as_of or date.today()
        horizon = max(1, min(int(horizon), 10))
        facts = self._annual_facts(db, company, as_of)
        revenue = self._fact_base(db, facts, "revenue", as_of)
        fcf = self._fact_base(db, facts, "free_cash_flow", as_of)
        net_income = self._fact_base(db, facts, "net_income", as_of)
        shares = self._fact_base(db, facts, "shares_diluted", as_of)

        drivers = self._driver_overrides(db, company, as_of)
        val_assumptions = self._valuation_assumptions(db, company, as_of)
        cagr = self._revenue_cagr(facts.get("revenue") or {})
        margin_anchor = self._margin_anchor(db, company, revenue, fcf, as_of)
        net_margin = self._net_margin(revenue, net_income)
        burn = margin_anchor.value is not None and margin_anchor.value < 0

        base_year = revenue.fiscal_year
        years = list(range(base_year + 1, base_year + horizon + 1)) if base_year else []

        price, price_date = self._current_price(db, company, as_of)

        scenarios: dict[str, dict[str, Any]] = {}
        for scenario in SCENARIOS:
            rows: list[dict[str, Any]] = []
            revenue_prev = revenue.value
            for year in years:
                growth = self._growth(
                    db,
                    company,
                    scenario,
                    year,
                    as_of=as_of,
                    drivers=drivers,
                    val_assumptions=val_assumptions,
                    cagr=cagr,
                    burn=burn,
                )
                margin = self._margin(
                    db,
                    company,
                    scenario,
                    year,
                    as_of=as_of,
                    drivers=drivers,
                    val_assumptions=val_assumptions,
                    anchor=margin_anchor,
                )
                if (
                    revenue_prev is not None
                    and growth.value is not None
                    and growth.value > -1
                ):
                    revenue_prev = revenue_prev * (1 + growth.value)
                    projected_revenue: float | None = revenue_prev
                else:
                    # Sin crecimiento valido la cadena se rompe: este ejercicio
                    # y los siguientes son N/D, nunca un arrastre del ultimo.
                    revenue_prev = None
                    projected_revenue = None
                projected_fcf = (
                    projected_revenue * margin.value
                    if projected_revenue is not None and margin.value is not None
                    else None
                )
                projected_eps = (
                    projected_revenue * net_margin.value / shares.value
                    if projected_revenue is not None
                    and net_margin.value is not None
                    and shares.value not in (None, 0)
                    else None
                )
                row_label = (
                    LABEL_INFERIDO
                    if projected_revenue is not None
                    else LABEL_ND
                )
                rows.append(
                    {
                        "ejercicio": year,
                        "ingresos": projected_revenue,
                        "fcf": projected_fcf,
                        "bps": projected_eps,
                        "etiqueta": row_label,
                        "etiquetas": {
                            "ingresos": LABEL_INFERIDO if projected_revenue is not None else LABEL_ND,
                            "fcf": LABEL_INFERIDO if projected_fcf is not None else LABEL_ND,
                            "bps": LABEL_INFERIDO if projected_eps is not None else LABEL_ND,
                        },
                        "crecimiento": growth.as_dict(),
                        "margen_fcf": margin.as_dict(),
                    }
                )
            scenarios[scenario] = {"proyecciones": rows}

        # Ancla por accion para el precio objetivo: FCF si es positivo, si no
        # ingresos, si no N/D. Con FCF negativo un multiplo de FCF no significa
        # nada; mejor N/D o el ancla de ingresos, declarada.
        anchor_kind: str | None = None
        anchor_base_ps: float | None = None
        if (
            fcf.value is not None
            and fcf.value > 0
            and shares.value not in (None, 0)
        ):
            anchor_kind = "fcf"
            anchor_base_ps = fcf.value / shares.value  # type: ignore[operator]
        elif (
            revenue.value is not None
            and revenue.value > 0
            and shares.value not in (None, 0)
        ):
            anchor_kind = "ingresos"
            anchor_base_ps = revenue.value / shares.value  # type: ignore[operator]

        projected_ps: dict[str, float | None] = {}
        for scenario in SCENARIOS:
            last = scenarios[scenario]["proyecciones"][-1] if years else None
            if last is None or anchor_kind is None or shares.value in (None, 0):
                projected_ps[scenario] = None
                continue
            anchor_value = last["fcf"] if anchor_kind == "fcf" else last["ingresos"]
            projected_ps[scenario] = (
                anchor_value / shares.value if anchor_value is not None else None
            )

        targets = self._scenario_targets(
            db, company, as_of, anchor_kind, anchor_base_ps, projected_ps, price, price_date
        )
        for scenario in SCENARIOS:
            scenarios[scenario]["precio_objetivo_5y"] = {
                **targets[scenario],
                "precio_actual": price,
                "precio_fecha": price_date,
            }
        # El aviso describe los valores crudos del modelo; el guard despues
        # retira de la publicacion lo incoherente o fuera de rango (N/D).
        aviso = self._coherence_warning(scenarios, years)
        guarded = self._apply_publishability_guard(targets, scenarios, years, price, price_date)
        for scenario in SCENARIOS:
            scenarios[scenario]["precio_objetivo_5y"] = {
                **guarded[scenario],
                "precio_actual": price,
                "precio_fecha": price_date,
            }

        return {
            "ticker": company.ticker,
            "model_type": MODEL_TYPE,
            "model_version": MODEL_VERSION,
            "generado_en": datetime.now(UTC).isoformat(),
            "as_of": as_of.isoformat(),
            "horizonte_anos": horizon,
            "ejercicio_base": base_year,
            "disclaimer": DISCLAIMER_ES,
            "base": {
                "ingresos": revenue.as_dict(),
                "fcf": fcf.as_dict(),
                "resultado_neto": net_income.as_dict(),
                "acciones": shares.as_dict(),
                "crecimiento_base": cagr.as_dict(),
                "margen_fcf_base": margin_anchor.as_dict(),
                "margen_neto_base": net_margin.as_dict(),
            },
            "ancla_precio_objetivo": anchor_kind,
            "escenarios": scenarios,
            "aviso_coherencia": aviso,
        }

    @staticmethod
    def _apply_publishability_guard(
        targets: dict[str, dict[str, Any]],
        scenarios: dict[str, dict[str, Any]],
        years: list[int],
        price: float | None,
        price_date: str | None,
    ) -> dict[str, dict[str, Any]]:
        """Un objetivo incoherente o fuera de rango pasa a N/D con razon, no solo aviso.

        1) Con precio fechado, un objetivo fuera de 0,25x-4x del precio actual
           es un artefacto del multiplo implicito, no una tesis: N/D.
        2) Si los objetivos que quedan no cumplen bear <= base <= bull, o los
           ingresos del ultimo ano no cumplen ese orden, ningun escenario es
           publicable: N/D en todos. Nunca se reordena ni se recorta.
        """
        out = {s_: dict(t) for s_, t in targets.items()}

        def _blank(scenario: str, reason: str) -> None:
            out[scenario].update({"valor": None, "etiqueta": LABEL_ND, "mos": None, "base": reason})

        if price is not None and price > 0 and price_date is not None:
            for scenario in SCENARIOS:
                value = out[scenario]["valor"]
                if value is not None and not (
                    PUBLISHABLE_MIN_RATIO * price <= value <= PUBLISHABLE_MAX_RATIO * price
                ):
                    _blank(
                        scenario,
                        "escenario fuera de rango (0,25x-4x del precio actual), no publicable",
                    )
        values = [out[s_]["valor"] for s_ in SCENARIOS]
        present = [v for v in values if v is not None]
        unordered = present != sorted(present)
        revenue_unordered = False
        if years:
            last_revenue = [scenarios[s_]["proyecciones"][-1]["ingresos"] for s_ in SCENARIOS]
            revenue_unordered = all(v is not None for v in last_revenue) and not (
                last_revenue[0] <= last_revenue[1] <= last_revenue[2]  # type: ignore[operator]
            )
        if unordered or revenue_unordered:
            for scenario in SCENARIOS:
                if out[scenario]["valor"] is not None:
                    _blank(scenario, "escenarios incoherentes (no cumplen bear <= base <= bull), no publicable")
        return out

    @staticmethod
    def _coherence_warning(
        scenarios: dict[str, dict[str, Any]], years: list[int]
    ) -> str | None:
        """bear <= base <= bull o aviso explicito; nunca se reordenan a escondidas."""
        problems: list[str] = []
        targets = [
            scenarios[s]["precio_objetivo_5y"]["valor"] for s in SCENARIOS
        ]
        if all(t is not None for t in targets) and not (
            targets[0] <= targets[1] <= targets[2]  # type: ignore[operator]
        ):
            problems.append("precio objetivo")
        if years:
            last_revenue = [
                scenarios[s]["proyecciones"][-1]["ingresos"] for s in SCENARIOS
            ]
            if all(v is not None for v in last_revenue) and not (
                last_revenue[0] <= last_revenue[1] <= last_revenue[2]  # type: ignore[operator]
            ):
                problems.append("ingresos proyectados")
        if not problems:
            return None
        return (
            f"los escenarios no quedan ordenados bear <= base <= bull en "
            f"{' y '.join(problems)}; se muestran los valores calculados, sin reordenar"
        )

    # -- persistencia y cuota --------------------------------------------------

    def persist(
        self,
        db: Session,
        company: Company,
        payload: dict[str, Any],
        *,
        commit: bool = True,
    ) -> ValuationModel:
        """Guarda el modelo (trace completo), salidas por escenario y filas anuales.

        Reutiliza ValuationModel/ValuationOutput con model_type='thesis_5y';
        las filas por ejercicio no caben en ValuationOutput (no tiene year ni
        revenue/fcf/eps) y van a thesis_projection_years. Un escenario con
        objetivo o MOS N/D NO genera ValuationOutput: grabar un 0 por defecto
        seria un valor inventado.
        """
        latest = db.scalar(
            select(ValuationModel)
            .where(ValuationModel.company_id == company.id)
            .order_by(desc(ValuationModel.version))
            .limit(1)
        )
        version = (latest.version + 1) if latest else 1
        # "final" exige al menos una salida persistible (objetivo + MOS contra
        # precio fechado). Un objetivo sin MOS fechado, o un motor bloqueado,
        # se conserva como draft: el trace lo explica, la etiqueta no miente.
        has_target = any(
            payload["escenarios"][s]["precio_objetivo_5y"]["valor"] is not None
            and payload["escenarios"][s]["precio_objetivo_5y"]["mos"] is not None
            for s in SCENARIOS
        )
        model = ValuationModel(
            company_id=company.id,
            model_type=MODEL_TYPE,
            version=version,
            status="final" if has_target else "draft",
            calculation_trace=payload,
        )
        db.add(model)
        db.flush()
        for scenario in SCENARIOS:
            target = payload["escenarios"][scenario]["precio_objetivo_5y"]
            if target["valor"] is None or target["mos"] is None:
                continue
            db.add(
                ValuationOutput(
                    valuation_model_id=model.id,
                    scenario=scenario,
                    value_per_share=Decimal(str(target["valor"])),
                    margin_of_safety=Decimal(str(target["mos"])),
                    output_payload=payload["escenarios"][scenario],
                )
            )
        day = datetime.now(UTC).date()
        tenant_id = db.info.get("tenant_id")
        # Idempotencia por dia: un recalculo sustituye las filas del dia, no
        # las apila (la UNIQUE tenant+company+scenario+year+day lo exige).
        db.execute(
            delete(ThesisProjectionYear).where(
                ThesisProjectionYear.company_id == company.id,
                ThesisProjectionYear.day == day,
                ThesisProjectionYear.tenant_id == tenant_id,
            )
        )
        for scenario in SCENARIOS:
            for row in payload["escenarios"][scenario]["proyecciones"]:
                growth_base = row["crecimiento"].get("base") or "N/D"
                db.add(
                    ThesisProjectionYear(
                        valuation_model_id=model.id,
                        company_id=company.id,
                        scenario=scenario,
                        fiscal_year=row["ejercicio"],
                        revenue=(
                            Decimal(str(row["ingresos"]))
                            if row["ingresos"] is not None
                            else None
                        ),
                        fcf=(
                            Decimal(str(row["fcf"]))
                            if row["fcf"] is not None
                            else None
                        ),
                        eps=(
                            Decimal(str(row["bps"]))
                            if row["bps"] is not None
                            else None
                        ),
                        label=row["etiqueta"],
                        source=f"crecimiento: {growth_base}"[:500],
                        as_of=date.fromisoformat(payload["as_of"]),
                        day=day,
                    )
                )
        if commit:
            db.commit()
            db.refresh(model)
        else:
            db.flush()
        return model

    def recalcs_today(self, db: Session) -> int:
        """Recalculos persistidos hoy (UTC) por el TENANT, no por empresa.

        La sesion ya filtra ValuationModel por tenant (TenantOwnedMixin);
        contar por empresa regalaba la cuota completa a cada ticker.
        """
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return db.scalar(
            select(func.count(ValuationModel.id)).where(
                ValuationModel.model_type == MODEL_TYPE,
                ValuationModel.created_at >= start,
                *tenant_filters(db, ValuationModel),
            )
        ) or 0

    def recalculate_within_quota(
        self,
        db: Session,
        company: Company,
        *,
        as_of: date | None = None,
    ) -> tuple[dict[str, Any], ValuationModel]:
        """Proyecta y persiste con la cuota del tenant, serializado.

        Mismo patron que llm_proposal_runner.save_within_quota: candado de
        proceso por (tenant, dia) + pg_advisory_xact_lock en Postgres, con el
        count DENTRO del candado tras un commit (sin instantanea vieja). Sin
        el candado, dos POST simultaneos leian la misma cuenta y ambos pasaban
        (o chocaban con la UNIQUE de las filas anuales del dia).
        """
        payload = self.project(db, company, as_of=as_of)
        db.commit()  # el count ve lo ya confirmado por otras sesiones
        with _recalc_lock(db):
            if db.get_bind().dialect.name == "postgresql":
                raw = f"thesis5y-quota:{db.info.get('tenant_id')}:{datetime.now(UTC).date()}".encode()
                key = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") >> 1
                db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})
            if self.recalcs_today(db) >= DAILY_RECALC_QUOTA:
                db.rollback()
                raise ProjectionQuotaExceeded(DAILY_RECALC_QUOTA)
            try:
                model = self.persist(db, company, payload)
            except Exception:
                db.rollback()
                raise
        return payload, model

    def latest_persisted(self, db: Session, company: Company) -> dict[str, Any] | None:
        model = db.scalar(
            select(ValuationModel)
            .where(
                ValuationModel.company_id == company.id,
                ValuationModel.model_type == MODEL_TYPE,
            )
            .order_by(desc(ValuationModel.version))
            .limit(1)
        )
        if model is None:
            return None
        return {
            "valuation_model_id": model.id,
            "version": model.version,
            "status": model.status,
            "created_at": model.created_at.isoformat() if model.created_at else None,
        }


def company_label(metric: str) -> str:
    return {
        "revenue": "ingresos",
        "free_cash_flow": "FCF",
        "net_income": "resultado neto",
        "shares_diluted": "acciones diluidas",
    }.get(metric, metric)


_recalc_guard = threading.Lock()
_recalc_locks: dict[tuple[Any, date], threading.Lock] = {}


def _recalc_lock(db: Session) -> threading.Lock:
    key = (db.info.get("tenant_id"), datetime.now(UTC).date())
    with _recalc_guard:
        return _recalc_locks.setdefault(key, threading.Lock())
