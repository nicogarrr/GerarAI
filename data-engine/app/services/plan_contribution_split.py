"""Reparto de la aportacion mensual del plan ponderado por nivel DCA.

«Este mes 225,00 EUR a POOL, 75,00 EUR a UBER». La cuota del plan se reparte
entre sus tickers:

- Base ``objetivos_ticker``: los objetivos del plan de tipo ``ticker`` (su
  ``target_pct`` es el peso base). Los objetivos por sector o clase de activo
  no son destinos de compra y no entran.
- Base ``posiciones_iguales``: sin objetivos por ticker, las posiciones vivas
  (cantidad > 0) a partes iguales.

Cada peso base se multiplica por el cuadrado del nivel DCA del motor
(``dca_signal_states``): 4X pesa 16, 3X 9, 2X 4, 1X 1 y las zonas de recorte
(-1/-2) pesan 0: no se aporta dinero nuevo a un valor que el motor manda
recortar. La cuota del mes no cambia: el nivel solo mueve el reparto.

Por que el cuadrado (backtest gerarai-dcaplano, 2-nov-2026, 600 carteras
aleatorias de 10-20 valores del S&P 500, mismo dinero y fechas que el DCA
plano): fuera de muestra (2013-2026) nivel² gana al DCA plano por +1,3 puntos
de TIR en el 82 % de las carteras, frente a +0,6 del peso ×nivel anterior; al
reves (1996-2012) +1,2, y gana en las 21 ventanas de 10 anos.

Valores poco volatiles (volatilidad anualizada del motor < 25 %, la misma
``vol`` de 36 meses que guarda ``dca_signal_states.metrics``): 2X-4X pesan como
1X. En ellos el nivel no anticipa nada: a 12 meses, frente al SPY, 2X-4X no
rinden mas que 1X (mediana 1996-2012: 1X +2,4, 2X +0,5, 3X +0,5, 4X -1,1 puntos;
2013-2025: -0,4 / -3,6 / -2,4 / +1,7), mientras que en los volatiles (> 40 %) 4X
rinde +14 / +16 puntos. Backtest gerarai-dcavalor1 (7-nov-2026, regla de
robustez fijada antes de mirar, 600 carteras por ventana frente a nivel² con
tope): gana en las 4 ventanas, +0,09 (1996-2012) y +0,29 (2013-2026) puntos de
TIR con 491 valores del S&P 500, +0,99 (2015-2020) y +0,64 (2021-2026) con 361;
gana en el 67-86 % de las carteras y la peor pierde menos de 3 puntos. Sin vol
(historia corta) o con un valor no legible, se mantiene nivel². Los recortes
siguen pesando 0 y 1X sigue siendo 1X.

Tope de concentracion: un ticker que ya pesa mas del doble de su peso base en
la cartera del plan (valor de mercado en divisa base de sus posiciones vivas,
sumando carteras) no recibe aportacion este mes; su parte va al resto. Mismo
backtest: el peso maximo mediano baja del 44 % al 39 % y conserva +1,1 puntos.
Solo se aplica con valores fiables (todas las posiciones vivas del plan con
valor > 0 en una misma divisa base) y nunca deja el mes sin destino: si el tope
dejaria todo a cero, se ignora.

Degrada limpio: si la tabla ``dca_signal_states`` no existe (el motor DCA aun
no esta desplegado) o un ticker no tiene nivel, ese ticker pesa como 1X y la
respuesta lo dice; nunca se inventa un nivel. Si todo esta en recorte, la
cuota queda sin asignar (liquidez) y se dice.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.models import Company, Position
from app.services.investment_plan_service import InvestmentPlanService

DCA_TABLE = "dca_signal_states"
# Peso = nivel² (ver docstring); los recortes no reciben aportacion.
DCA_MULTIPLIER: dict[int, int] = {4: 16, 3: 9, 2: 4, 1: 1, -1: 0, -2: 0}
DCA_LABELS: dict[int, str] = {
    4: "4X DCA",
    3: "3X DCA",
    2: "2X DCA",
    1: "1X DCA",
    -1: "RECORTE LIGERO",
    -2: "RECORTE FUERTE",
}
_CENT = Decimal("0.01")
# Un nivel DCA vale para el mes en formacion o el ultimo confirmado. Uno mas
# viejo (ticker que dejo de evaluarse, motor parado) no dice nada de este mes.
DCA_MAX_AGE_MONTHS = 1
# Vol anualizada (fraccion) por debajo de la cual 2X-4X pesan como 1X (ver docstring).
LOW_VOLATILITY_THRESHOLD = 0.25
# Sin aportacion nueva a un ticker que pesa mas de CONCENTRATION_CAP x su peso base.
CONCENTRATION_CAP = Decimal(2)


def _today() -> date:
    # Mes del usuario (Europe/Madrid): el servidor corre en UTC.
    return local_today()


def _months_old(period: str | None, today: date) -> int | None:
    """Meses entre ``period`` (YYYY-MM) y el mes de ``today``; None si no se puede leer."""
    try:
        year, month = (int(part) for part in str(period).split("-")[:2])
    except (TypeError, ValueError):
        return None
    if not 1 <= month <= 12:
        return None
    return (today.year - year) * 12 + (today.month - month)


@dataclass(frozen=True)
class SplitCandidate:
    ticker: str
    base_weight: Decimal
    dca_level: int | None = None
    dca_period: str | None = None
    dca_status: str | None = None
    dca_stale: bool = False
    concentration_capped: bool = False
    market_share_pct: Decimal | None = None
    base_share_pct: Decimal | None = None
    # Volatilidad anualizada del motor (metrics["vol"]); None = desconocida.
    dca_vol: float | None = None

    @property
    def low_volatility(self) -> bool:
        """Nivel de compra 2X-4X en un valor poco volatil: pesa como 1X."""
        if self.dca_level is None or int(self.dca_level) < 2:
            return False
        vol = _volatility(self.dca_vol)
        return vol is not None and vol < LOW_VOLATILITY_THRESHOLD


def _money_es(value: Decimal) -> str:
    """225.5 -> «225,50» (miles con punto)."""
    text = f"{value.quantize(_CENT, rounding=ROUND_HALF_UP):,.2f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _pct_es(value: Decimal) -> str:
    """80 -> «80,0»."""
    return f"{value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}".replace(".", ",")


def _volatility(raw: object) -> float | None:
    """Vol anualizada legible (> 0 y finita) o None."""
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _multiplier(level: int | None) -> int:
    if level is None:
        return 1
    return DCA_MULTIPLIER.get(int(level), 1)


def _candidate_multiplier(candidate: SplitCandidate) -> int:
    return 1 if candidate.low_volatility else _multiplier(candidate.dca_level)


def _reason(candidate: SplitCandidate) -> str:
    level = candidate.dca_level
    if candidate.concentration_capped:
        if level is not None:
            label = DCA_LABELS.get(int(level), f"nivel {level}")
        else:
            label = "nivel DCA caducado" if candidate.dca_stale else "sin nivel DCA"
        share = _pct_es(candidate.market_share_pct or Decimal(0))
        base = _pct_es(candidate.base_share_pct or Decimal(0))
        return (
            f"{label}: ya pesa el {share} % del plan, más del doble de su peso objetivo ({base} %); "
            "este mes no recibe aportación"
        )
    if candidate.dca_stale:
        return f"nivel DCA caducado (mes {candidate.dca_period or 's/d'}): peso normal (1X) hasta reevaluar"
    if level is None:
        return "sin nivel DCA: peso normal (1X)"
    label = DCA_LABELS.get(int(level), f"nivel {level}")
    if _multiplier(level) == 0:
        return f"{label}: zona de recorte, este mes no recibe aportación"
    if candidate.low_volatility:
        vol_pct = _pct_es(Decimal(str(_volatility(candidate.dca_vol))) * 100)
        return (
            f"{label}: peso ×1 (poco volátil, vol {vol_pct} %: en estos valores 2X–4X "
            "no ha rendido más que 1X)"
        )
    return f"{label}: peso ×{_multiplier(level)}"


def split_contribution(amount: Decimal, candidates: list[SplitCandidate]) -> dict[str, Any]:
    """Reparto puro: importes al centimo y la suma cuadra con ``amount``."""
    amount = Decimal(amount).quantize(_CENT, rounding=ROUND_HALF_UP)

    def _weight(candidate: SplitCandidate) -> Decimal:
        if candidate.concentration_capped:
            return Decimal(0)
        return max(Decimal(candidate.base_weight), Decimal(0)) * _candidate_multiplier(candidate)

    if candidates and sum((_weight(c) for c in candidates), Decimal(0)) <= 0:
        # El tope nunca deja el mes sin destino: si todo lo demas esta en recorte, se ignora.
        candidates = [replace(c, concentration_capped=False) for c in candidates]
    effective = [(candidate, _weight(candidate)) for candidate in candidates]
    total_weight = sum((weight for _, weight in effective), Decimal(0))
    amounts: list[Decimal] = []
    if total_weight > 0:
        amounts = [
            (amount * weight / total_weight).quantize(_CENT, rounding=ROUND_HALF_UP)
            for _, weight in effective
        ]
        residual = amount - sum(amounts, Decimal(0))
        if residual and amounts:
            # El centimo que sobra o falta va al de mayor peso (el ultimo en empate).
            biggest = max(range(len(effective)), key=lambda i: (effective[i][1], i))
            amounts[biggest] += residual
    else:
        amounts = [Decimal(0) for _ in effective]

    allocations = []
    for (candidate, weight), value in zip(effective, amounts, strict=True):
        share = (weight / total_weight * 100) if total_weight > 0 else Decimal(0)
        allocations.append(
            {
                "ticker": candidate.ticker,
                "amount": float(value),
                "share_pct": float(share.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)),
                "base_weight": float(candidate.base_weight),
                "dca_level": candidate.dca_level,
                "dca_label": DCA_LABELS.get(int(candidate.dca_level))
                if candidate.dca_level is not None
                else None,
                "dca_period": candidate.dca_period,
                "dca_status": candidate.dca_status,
                "dca_stale": candidate.dca_stale,
                "multiplier": _candidate_multiplier(candidate),
                "low_volatility": candidate.low_volatility,
                "volatility_pct": (
                    round(vol * 100, 1) if (vol := _volatility(candidate.dca_vol)) is not None else None
                ),
                "concentration_capped": candidate.concentration_capped,
                "market_share_pct": _pct_float(candidate.market_share_pct),
                "base_share_pct": _pct_float(candidate.base_share_pct),
                "reason": _reason(candidate),
            }
        )
    if not candidates:
        status = "no_candidates"
    elif total_weight <= 0:
        status = "all_trim"
    else:
        status = "ok"
    allocated = sum(amounts, Decimal(0))
    return {
        "status": status,
        "allocations": allocations,
        "unallocated": float(amount - allocated),
    }


def _pct_float(value: Decimal | None) -> float | None:
    return None if value is None else float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _plan_market_values(db: Session, companies: dict[str, Company]) -> dict[str, Decimal] | None:
    """Valor de mercado en divisa base de las posiciones vivas de cada ticker del plan.

    None si no es fiable: alguna posicion viva sin valor (o con valor 0, sin
    precio), divisas base distintas o nada invertido. Entonces no hay tope.
    """
    tickers_by_id = {company.id: ticker for ticker, company in companies.items()}
    if not tickers_by_id:
        return None
    statement = select(Position.company_id, Position.market_value_base, Position.base_currency).where(
        Position.company_id.in_(list(tickers_by_id)), Position.quantity > 0
    )
    tenant_id = db.info.get("tenant_id")
    if tenant_id is not None:
        # Segunda capa sobre el filtro de tenant de la sesion: solo posiciones del usuario.
        statement = statement.where(Position.tenant_id == tenant_id)
    rows = db.execute(statement).all()
    values: dict[str, Decimal] = {}
    base_currencies: set[str] = set()
    for company_id, value, base_currency in rows:
        if value is None or Decimal(value) <= 0:
            return None
        base_currencies.add(str(base_currency or "").upper())
        ticker = tickers_by_id[company_id]
        values[ticker] = values.get(ticker, Decimal(0)) + Decimal(value)
    if len(base_currencies) != 1 or sum(values.values(), Decimal(0)) <= 0:
        return None
    return values


def _apply_concentration_cap(
    candidates: list[SplitCandidate], values: dict[str, Decimal] | None
) -> list[SplitCandidate]:
    if values is None:
        return candidates
    total_value = sum(values.values(), Decimal(0))
    total_base = sum((max(Decimal(c.base_weight), Decimal(0)) for c in candidates), Decimal(0))
    if total_value <= 0 or total_base <= 0:
        return candidates
    capped: list[SplitCandidate] = []
    for candidate in candidates:
        share = values.get(candidate.ticker, Decimal(0)) / total_value * 100
        base = max(Decimal(candidate.base_weight), Decimal(0)) / total_base * 100
        capped.append(
            replace(
                candidate,
                concentration_capped=share > CONCENTRATION_CAP * base,
                market_share_pct=share,
                base_share_pct=base,
            )
        )
    return capped


def dca_table_available(db: Session) -> bool:
    try:
        return inspect(db.get_bind()).has_table(DCA_TABLE)
    except Exception:  # noqa: BLE001 - sin tabla legible = sin nivel DCA, nunca rompe el plan
        return False


def _dca_rows(db: Session) -> list[Any] | None:
    """Filas de ``dca_signal_states`` del tenant; None si el motor no esta desplegado."""
    if not dca_table_available(db):
        return None
    table = sa.table(
        DCA_TABLE,
        sa.column("id"),
        sa.column("tenant_id"),
        sa.column("symbol"),
        sa.column("company_id"),
        sa.column("level"),
        sa.column("status"),
        sa.column("period"),
        sa.column("metrics", sa.JSON),
    )
    statement = select(
        table.c.id,
        table.c.symbol,
        table.c.company_id,
        table.c.level,
        table.c.status,
        table.c.period,
        table.c.metrics,
    )
    tenant_id = db.info.get("tenant_id")
    if tenant_id is not None:
        statement = statement.where(table.c.tenant_id == tenant_id)
    try:
        return list(db.execute(statement).all())
    except Exception:  # noqa: BLE001 - esquema distinto al esperado: se degrada a "sin nivel"
        return None


def _row_volatility(row: Any) -> float | None:
    """``metrics["vol"]`` de la fila del motor; cualquier forma ilegible = None."""
    if row is None:
        return None
    metrics = getattr(row, "metrics", None)
    if isinstance(metrics, str):
        try:
            metrics = json.loads(metrics)
        except ValueError:
            return None
    if not isinstance(metrics, dict):
        return None
    return _volatility(metrics.get("vol"))


def build_contribution_split(db: Session) -> dict[str, Any]:
    service = InvestmentPlanService()
    plan = service.get_plan(db)
    if plan is None:
        return {"plan_exists": False}

    currency = (plan.monthly_contribution_currency or "").upper() or None
    notes: list[str] = []
    ticker_targets = [
        target
        for target in (plan.target_allocations or [])
        if target.get("kind") == "ticker"
        and str(target.get("label") or "").strip()
        and Decimal(str(target.get("target_pct") or 0)) > 0
    ]
    if ticker_targets:
        basis = "objetivos_ticker"
        weights: dict[str, Decimal] = {}
        for target in ticker_targets:
            ticker = str(target["label"]).strip().upper()
            weights[ticker] = weights.get(ticker, Decimal(0)) + Decimal(str(target["target_pct"]))
        companies = {
            company.ticker.upper(): company
            for company in db.scalars(select(Company).where(Company.ticker.in_(list(weights)))).all()
        }
    else:
        basis = "posiciones_iguales"
        rows = db.execute(
            select(Position, Company)
            .join(Company, Position.company_id == Company.id)
            .where(Position.quantity > 0)
        ).all()
        companies = {}
        for _, company in rows:
            companies.setdefault(company.ticker.upper(), company)
        weights = {ticker: Decimal(1) for ticker in companies}
        if weights:
            notes.append(
                "El plan no tiene objetivos por ticker: se reparte a partes iguales entre las posiciones vivas."
            )

    dca_rows = _dca_rows(db)
    dca_available = dca_rows is not None
    by_company = {row.company_id: row for row in dca_rows or [] if row.company_id is not None}
    by_symbol = {str(row.symbol).upper(): row for row in dca_rows or []}
    if not dca_available:
        notes.append(
            "El motor DCA no está desplegado todavía: el reparto sigue solo los pesos del plan (todos como 1X)."
        )

    today = _today()
    candidates: list[SplitCandidate] = []
    for ticker, weight in weights.items():
        company = companies.get(ticker)
        row = (by_company.get(company.id) if company else None) or by_symbol.get(ticker)
        level = int(row.level) if row is not None and row.level is not None else None
        period = str(row.period) if row is not None and row.period is not None else None
        stale = False
        if level is not None:
            age = _months_old(period, today)
            # Sin mes legible, EN EL FUTURO (dato corrupto: ese mes aun no se
            # puede haber evaluado) o de hace mas de un mes: no se usa (1X).
            stale = age is None or age < 0 or age > DCA_MAX_AGE_MONTHS
        candidates.append(
            SplitCandidate(
                ticker=ticker,
                base_weight=weight,
                dca_level=None if stale else level,
                dca_period=period,
                dca_status=str(row.status) if row is not None and row.status is not None else None,
                dca_stale=stale,
                dca_vol=_row_volatility(row),
            )
        )
    stale_tickers = [c.ticker for c in candidates if c.dca_stale]
    if stale_tickers:
        notes.append(
            "Nivel DCA de hace más de un mes en "
            + ", ".join(stale_tickers)
            + ": pesa como 1X hasta que se vuelva a evaluar."
        )
    if dca_available and candidates and all(c.dca_level is None and not c.dca_stale for c in candidates):
        notes.append("Ningún ticker del plan tiene nivel DCA calculado: todos pesan como 1X.")

    low_vol_tickers = [c.ticker for c in candidates if c.low_volatility]
    if low_vol_tickers:
        many = len(low_vol_tickers) > 1
        notes.append(
            ("Poco volátiles" if many else "Poco volátil")
            + f" (vol < {int(LOW_VOLATILITY_THRESHOLD * 100)} %): "
            + ", ".join(low_vol_tickers)
            + (" pesan como 1X aunque estén" if many else " pesa como 1X aunque esté")
            + " en 2X–4X; en estos valores el nivel no ha rendido más (backtest)."
        )

    candidates = _apply_concentration_cap(candidates, _plan_market_values(db, companies))
    amount = Decimal(plan.monthly_contribution)
    result = split_contribution(amount, candidates)
    capped_tickers = [row["ticker"] for row in result["allocations"] if row["concentration_capped"]]
    if capped_tickers:
        notes.append(
            "Sin aportación nueva este mes a "
            + ", ".join(capped_tickers)
            + (": ya pesan" if len(capped_tickers) > 1 else ": ya pesa")
            + " más del doble de su peso objetivo en el plan."
        )
    unit = f" {currency}" if currency else ""
    summary = None
    funded = [row for row in result["allocations"] if row["amount"] > 0]
    if result["status"] == "ok" and funded:
        parts = [f"{_money_es(Decimal(str(row['amount'])))}{unit} a {row['ticker']}" for row in funded]
        summary = "Este mes " + ", ".join(parts)
    elif result["status"] == "all_trim":
        summary = (
            f"Este mes todo el plan está en zona de recorte: los {_money_es(amount)}{unit} "
            "quedan en liquidez."
        )
    if currency is None:
        notes.append("La divisa de la aportación no está registrada en el plan.")
    from app.services.savings_projection import savings_contract

    return {
        "savings_projection": savings_contract(db),
        "plan_exists": True,
        "amount": float(amount),
        "currency": currency,
        "basis": basis,
        "dca_available": dca_available,
        "summary": summary,
        "notes": notes,
        **result,
    }
