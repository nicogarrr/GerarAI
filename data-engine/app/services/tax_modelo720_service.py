"""Modelo 720 (declaración informativa de bienes y derechos en el extranjero).

Chequeo de umbrales POR CATEGORÍA (50.000 €), que es como manda la norma:
  - Valores (acciones, fondos, bonos depositados en el extranjero): valor a
    31 de diciembre.
  - Cuentas: mayor entre saldo a 31/12 y saldo medio del 4.º trimestre.
  - Bienes inmuebles: no aplica a datos de bróker (siempre sin datos).

Enfoque de referencia: DeclaRenta (GPL-3.0) — reimplementación del criterio
normativo, sin copia de código.

Honestidad (sin verde falso), dictamen del auditor incorporado:
- Las posiciones se reconstruyen desde los snapshots diarios del PORTFOLIO
  ACTIVO (``PositionDailySnapshot``) más recientes a 31/12. La antigüedad se
  evalúa PARTIDA A PARTIDA: un snapshot reciente nunca certifica a otro
  antiguo; cada partida con snapshot viejo queda fuera del total y la
  categoría pasa a "desconocido".
- El umbral es en EUR: si la divisa base del portfolio no es EUR no se
  evalúa (sin tipo de cambio oficial a 31/12 no hay conversión fiable) y
  todas las categorías quedan "desconocido".
- La custodia extranjera NO se infiere del origen de importación (IBKR):
  importar de un bróker no acredita dónde está depositado cada valor. Solo
  computa cuando el tenant declara el país de depósito/gestión en
  ``tax_declarant.custody_country`` (dato fiscal personal del tenant); sin
  él, las partidas van a ``foreign_unverified`` y la categoría es
  "desconocido".
- Una posición sin valoración en base queda fuera del total, listada en
  ``unvalued``. Un corto es una deuda, no un bien: no suma (``short_positions``).
- Saldo medio del 4.º trimestre: se reconstruye con las capturas diarias de
  caja (``CashDailySnapshot``, al menos una por semana del 1/10 al 31/12) y
  se convierte al tipo del 31/12 (FAQ AEAT del 720). Sin cobertura queda
  ``average_q4_missing`` y la categoría no puede salir «por debajo».
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CashBalance,
    CashDailySnapshot,
    Company,
    Portfolio,
    PortfolioDailySnapshot,
    Position,
    PositionDailySnapshot,
    Tenant,
)
from app.services.portfolio_fx_service import PortfolioFXService

THRESHOLD_720 = Decimal("50000")

# Máxima antigüedad del snapshot aceptable para afirmar el valor a 31/12,
# evaluada PARTIDA A PARTIDA (una posición al 31/12 no certifica a otra de junio).
SNAPSHOT_MAX_LAG_DAYS = 10


#: Hueco máximo entre dos capturas de saldo para reconstruir el saldo diario
#: del 4.º trimestre (el saldo de un día sin captura es el de la última).
Q4_MAX_GAP_DAYS = 7


def q4_average_detail(points: list[tuple[date, Decimal]], fiscal_year: int) -> dict | None:
    """Saldo medio del 4.º trimestre (1/10–31/12) en la divisa de la cuenta.

    Media de los saldos DIARIOS del trimestre (92 días): el saldo de un día
    sin captura es el de la última captura anterior. Solo se calcula con
    cobertura suficiente: una captura el 1/10 o anterior (como mucho
    ``Q4_MAX_GAP_DAYS`` antes), ningún hueco mayor entre capturas y la última
    a menos de ese margen del 31/12. Sin cobertura devuelve ``None`` (no se
    inventa el saldo medio, ni se aplica hacia atrás un saldo posterior).

    Devuelve ``average`` (Decimal), ``observed_days`` (días del trimestre con
    captura propia), ``carried_days`` (días cuyo saldo se arrastra de una
    captura anterior) y ``estimate``: ``True`` en cuanto un solo día se
    arrastra. Con capturas semanales la media es una ESTIMACIÓN (el saldo
    entre capturas no se observó); solo con captura de los 92 días es el
    saldo medio diario exacto.

    Base: art. 42 bis.4.b RD 1065/2007 y Orden HAP/72/2013 (saldo a 31/12 y
    saldo medio del último trimestre); FAQ AEAT del 720: ambos se convierten
    al tipo de cambio vigente a 31/12 (eso lo hace el llamador).
    """
    q_start = date(fiscal_year, 10, 1)
    q_end = date(fiscal_year, 12, 31)
    by_day: dict[date, Decimal] = {}
    for day, balance in points:
        if q_start - timedelta(days=Q4_MAX_GAP_DAYS) <= day <= q_end:
            by_day[day] = Decimal(str(balance))
    if not by_day:
        return None
    days = sorted(by_day)
    # El primer dato debe ser del 1/10 o ANTERIOR (hasta el margen): un saldo
    # posterior al 1/10 no se puede aplicar hacia atras a dias ya transcurridos.
    if days[0] > q_start or (q_start - days[0]).days > Q4_MAX_GAP_DAYS:
        return None
    if (q_end - days[-1]).days > Q4_MAX_GAP_DAYS:
        return None
    if any((b - a).days > Q4_MAX_GAP_DAYS for a, b in zip(days, days[1:], strict=False)):
        return None
    total = Decimal("0")
    current = by_day[days[0]]
    idx = 0
    observed = 0
    n_days = (q_end - q_start).days + 1
    for offset in range(n_days):
        day = q_start + timedelta(days=offset)
        while idx < len(days) and days[idx] <= day:
            current = by_day[days[idx]]
            idx += 1
        if day in by_day:
            observed += 1
        total += current
    return {
        "average": total / Decimal(n_days),
        "observed_days": observed,
        "carried_days": n_days - observed,
        "estimate": observed < n_days,
    }


def q4_average_native(points: list[tuple[date, Decimal]], fiscal_year: int) -> Decimal | None:
    """Solo el saldo medio de :func:`q4_average_detail` (``None`` sin cobertura)."""
    detail = q4_average_detail(points, fiscal_year)
    return None if detail is None else detail["average"]


def _money(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _latest_snapshots_before(
    db: Session, model, partition_col, year_end: date, portfolio_ids: list
) -> list:
    """Último snapshot por partición (empresa/divisa) en las carteras del DECLARANTE.

    La obligación del 720 es por declarante, no por cartera: se agregan
    TODAS las carteras del tenant. La partición por empresa/divisa evita que
    el snapshot más reciente de una cartera eclipse las filas de otra.
    """
    # Partición por (cartera, empresa/divisa): sin la cartera en el GROUP
    # BY, el snapshot más reciente de UNA cartera eclipse la fila de OTRA
    # (AAPL 30k al 30/12 en A + AAPL 25k al 31/12 en B = 55k, no 25k).
    latest_dates = (
        select(
            model.portfolio_id,
            partition_col,
            func.max(model.snapshot_date).label("max_date"),
        )
        .where(model.snapshot_date <= year_end)
        .where(model.portfolio_id.in_(portfolio_ids))
        .group_by(model.portfolio_id, partition_col)
        .subquery()
    )
    return list(
        db.scalars(
            select(model)
            .where(model.portfolio_id.in_(portfolio_ids))
            .join(
                latest_dates,
                (model.portfolio_id == latest_dates.c.portfolio_id)
                & (partition_col == latest_dates.c[1])
                & (model.snapshot_date == latest_dates.c.max_date),
            )
        )
    )


def _declared_custody_map(db: Session, tenant_id) -> dict[str, str]:
    """Custodia declarada POR PARTIDA (metadata del tenant, ``tax_declarant.custody``).

    Claves: ISIN (o ticker si no hay ISIN) para valores, ``cash:<DIVISA>``
    para cuentas. Valores: código ISO2 del depositario/gestor. "ES" NO es
    extranjero: la partida queda fuera del 720 como nacional. Un país único
    para toda la cartera sería un dato falso en carteras mixtas (dictamen
    del auditor): no hay valor por defecto.
    """
    if tenant_id is None:
        return {}
    tenant = db.get(Tenant, tenant_id)
    declarant = (tenant.metadata_ or {}).get("tax_declarant") if tenant else None
    if not isinstance(declarant, dict):
        return {}
    raw = declarant.get("custody")
    if not isinstance(raw, dict):
        return {}
    return {
        str(k).upper(): str(v).strip().upper()
        for k, v in raw.items()
        if isinstance(v, str) and len(str(v).strip()) == 2
    }


class Modelo720Service:
    """Chequeo de umbrales del Modelo 720 para un ejercicio.

    Tri-estado por categoría: ``exceeds`` es True/False solo con datos
    suficientes; cualquier laguna (partida con snapshot antiguo, valoración
    ausente, custodia extranjera no declarada, base no EUR, saldo medio Q4
    desconocido) lo deja en None con ``status="desconocido"`` — una
    respuesta construida sobre datos parciales sería un falso verde.
    """

    def check_thresholds(self, db: Session, fiscal_year: int) -> dict:
        year_end = date(fiscal_year, 12, 31)
        portfolio = PortfolioFXService().portfolio(db)

        base: dict = {
            "fiscal_year": fiscal_year,
            "threshold_base": _money(THRESHOLD_720),
            "base_currency": None,
            "custody_country": None,
            "unvalued": [],
            "foreign_unverified": [],
            "short_positions": [],
            "stale_snapshots": [],
            "domestic_assets": [],
            "zero_balance_accounts": [],
            "incomplete": False,
        }

        def _unknown_category(reason: str, **extra) -> dict:
            return {
                "exceeds": None,
                "status": "desconocido",
                "total_base": None,
                "snapshot_lag_days": None,
                "reasons": [reason],
                **extra,
            }

        if portfolio is None:
            base["categories"] = {
                "valores": _unknown_category(
                    "Sin portfolio activo: no hay snapshots que evaluar.",
                    positions=[], missing_isin=[],
                    custody="por_partida",
                ),
                "cuentas": _unknown_category(
                    "Sin portfolio activo: no hay snapshots que evaluar.",
                    balances=[], average_q4_missing=True,
                    custody="por_partida",
                ),
                "inmuebles": _inmuebles(),
            }
            base["notas"] = _notas()
            return base

        base["base_currency"] = portfolio.base_currency
        if (portfolio.base_currency or "").upper() != "EUR":
            base["categories"] = {
                "valores": _unknown_category(
                    f"La divisa base del portfolio es {portfolio.base_currency}, "
                    "no EUR: sin tipo de cambio oficial a 31/12 no hay "
                    "conversión fiable y el umbral de 50.000 € no se evalúa.",
                    positions=[], missing_isin=[],
                    custody="por_partida",
                ),
                "cuentas": _unknown_category(
                    f"La divisa base del portfolio es {portfolio.base_currency}, "
                    "no EUR: sin tipo de cambio oficial a 31/12 no hay "
                    "conversión fiable y el umbral de 50.000 € no se evalúa.",
                    balances=[], average_q4_missing=True,
                    custody="por_partida",
                ),
                "inmuebles": _inmuebles(),
            }
            base["incomplete"] = True
            base["notas"] = _notas()
            return base

        custody_map = _declared_custody_map(db, portfolio.tenant_id)
        base["custody_country"] = None  # ya no hay país único: es por partida
        custody_state = "por_partida"

        unvalued: list[dict] = []
        foreign_unverified: list[dict] = []
        short_positions: list[dict] = []
        stale_snapshots: list[dict] = []
        domestic_assets: list[dict] = []

        # Carteras del DECLARANTE (la obligación del 720 es por declarante,
        # no por cartera): se agregan todas las del tenant.
        tenant_portfolios = list(db.scalars(
            select(Portfolio).where(Portfolio.tenant_id == portfolio.tenant_id)
        ))
        # Gate EUR POR CARTERA: una cartera con base distinta de EUR no se
        # suma como si fuera EUR (sin FX oficial a 31/12 no hay conversión
        # fiable); sus partidas quedan fuera y la categoría, no concluyente.
        eur_portfolio_ids = [
            p.id for p in tenant_portfolios
            if (p.base_currency or "").upper() == "EUR"
        ]
        non_eur_portfolios = [
            p for p in tenant_portfolios
            if (p.base_currency or "").upper() != "EUR"
        ]
        portfolio_ids = eur_portfolio_ids

        # Provenance de valoración HISTÓRICA, ligada al snapshot original
        # (metadata_.missing_pricing del PortfolioDailySnapshot): las filas
        # listadas llevan la fecha del precio/saldo EN LA CAPTURA; las no
        # listadas tenían as_of == fecha del snapshot. El as_of de las filas
        # VIVAS no autentica el histórico (un refresh posterior lo reescribe).
        def _historical_price_dates(rows, id_field: str) -> tuple[dict, set]:
            """(fechas históricas, snapshots padre SIN provenance probada).

            El servicio de snapshots siempre escribe la clave
            ``missing_pricing`` (aunque sea lista vacía): su AUSENCIA en un
            snapshot heredado no prueba que as_of == fecha del snapshot.
            """
            snap_ids = {r.portfolio_snapshot_id for r in rows}
            result: dict = {}
            unproven: set = set()
            for parent in db.scalars(
                select(PortfolioDailySnapshot).where(PortfolioDailySnapshot.id.in_(snap_ids))
            ) if snap_ids else []:
                metadata = parent.metadata_ or {}
                if "missing_pricing" not in metadata:
                    unproven.add(parent.id)
                    continue
                for entry in metadata.get("missing_pricing") or []:
                    key = entry.get(id_field)
                    val = entry.get("valuation_date")
                    if key is not None and val:
                        result[(parent.id, key)] = val
            return result, unproven

        def _price_date_ok(
            ticker: str, snap: date, historical: str | None,
            *,
            provenance_unproven: bool = False,
        ) -> bool:
            """True si la valoración afirma el cierre con fecha propia."""
            if provenance_unproven:
                stale_snapshots.append({
                    "ticker": ticker,
                    "snapshot_date": snap.isoformat(),
                    "reason": (
                        "Snapshot heredado sin provenance de valoración "
                        "(sin clave 'missing_pricing' en su metadata): no "
                        "consta la fecha del precio en la captura; fuera "
                        "del total."
                    ),
                })
                return False
            lag = (year_end - snap).days
            if lag > SNAPSHOT_MAX_LAG_DAYS:
                stale_snapshots.append({
                    "ticker": ticker,
                    "snapshot_date": snap.isoformat(),
                    "lag_days": lag,
                    "reason": (
                        f"Snapshot de {snap.isoformat()} ({lag} días antes "
                        "del cierre): demasiado antiguo para afirmar el valor a "
                        "31/12 de ESTA partida; fuera del total."
                    ),
                })
                return False
            if historical is not None:
                try:
                    price_date = date.fromisoformat(historical)
                except ValueError:
                    price_date = None
                if (
                    price_date is None
                    or price_date > year_end
                    or (year_end - price_date).days > SNAPSHOT_MAX_LAG_DAYS
                ):
                    stale_snapshots.append({
                        "ticker": ticker,
                        "snapshot_date": snap.isoformat(),
                        "price_as_of": historical,
                        "reason": (
                            "La valoración de la captura está fechada "
                            f"{historical}: no afirma el valor a 31/12 "
                            "(provenance histórica del snapshot). Fuera del total."
                        ),
                    })
                    return False
            return True

        # --- Valores (categoría V) ---
        positions = _latest_snapshots_before(
            db, PositionDailySnapshot, PositionDailySnapshot.company_id,
            year_end, portfolio_ids,
        )
        position_price_dates, position_unproven = _historical_price_dates(
            positions, "company_id"
        )
        company_ids = [p.company_id for p in positions]
        companies = {
            c.id: c
            for c in db.scalars(select(Company).where(Company.id.in_(company_ids)))
        } if company_ids else {}

        valores_total = Decimal("0")
        valores_rows = []
        missing_isin = []
        valores_max_date: date | None = None
        for position in positions:
            company = companies.get(position.company_id)
            ticker = company.ticker if company else f"company-{position.company_id}"
            if valores_max_date is None or position.snapshot_date > valores_max_date:
                valores_max_date = position.snapshot_date
            if not _price_date_ok(
                ticker,
                position.snapshot_date,
                position_price_dates.get(
                    (position.portfolio_snapshot_id, position.company_id)
                ),
                provenance_unproven=position.portfolio_snapshot_id in position_unproven,
            ):
                continue
            value_base = position.market_value_base
            if value_base is None:
                unvalued.append({
                    "ticker": ticker,
                    "snapshot_date": position.snapshot_date.isoformat(),
                    "reason": "Sin tipo de cambio a fecha del snapshot: fuera del total EUR, valorar a mano.",
                })
                continue
            amount = Decimal(str(value_base))
            if amount < 0:
                # Un corto es una deuda, no un bien o derecho declarable:
                # no suma al umbral (abs() inflaría el patrimonio).
                short_positions.append({
                    "ticker": ticker,
                    "snapshot_date": position.snapshot_date.isoformat(),
                    "value_base": _money(amount),
                    "reason": "Posición corta (valor negativo): no es un bien en el extranjero a efectos del 720.",
                })
                continue
            isin = company.isin if company else None
            custody = custody_map.get((isin or ticker).upper())
            if custody is None:
                foreign_unverified.append({
                    "ticker": ticker,
                    "snapshot_date": position.snapshot_date.isoformat(),
                    "reason": (
                        "Custodia no declarada para esta partida: importar del "
                        "bróker no acredita dónde está depositada. Declara "
                        "tax_declarant.custody (ISIN/ticker → país ISO2) en la "
                        "metadata del tenant; mientras tanto, fuera del total."
                    ),
                })
                continue
            if custody == "ES":
                # España NO es extranjero a efectos del 720: fuera del modelo,
                # listada para transparencia (nunca cuenta como extranjera).
                domestic_assets.append({
                    "ticker": ticker,
                    "isin": isin,
                    "value_base": _money(amount),
                    "reason": "Custodia declarada en España: no es bien en el extranjero; no computa en el 720.",
                })
                continue
            valores_total += amount
            if not isin:
                missing_isin.append(ticker)
            valores_rows.append({
                "ticker": ticker,
                "name": company.name if company else ticker,
                "isin": isin,
                "custody_country": custody,
                "snapshot_date": position.snapshot_date.isoformat(),
                "quantity": _money(Decimal(str(position.quantity))),
                "value_base": _money(amount),
            })

        # --- Cuentas (categoría C) ---
        cash_rows = _latest_snapshots_before(
            db, CashDailySnapshot, CashDailySnapshot.currency,
            year_end, portfolio_ids,
        )
        cash_price_dates, cash_unproven = _historical_price_dates(
            cash_rows, "cash_currency"
        )
        cuentas_total = Decimal("0")
        cuentas_detail = []
        cuentas_max_date: date | None = None
        # Saldo medio del 4.º trimestre (convertido al tipo del 31/12).
        q4_total = Decimal("0")
        q4_rows = 0
        q4_unknown: list[str] = []
        # Cuentas cuyo saldo medio arrastra capturas (no hay saldo de cada día).
        q4_estimated: list[str] = []

        def _q4_native(cash) -> dict | None:
            points = [
                (snap.snapshot_date, snap.balance_native)
                for snap in db.scalars(
                    select(CashDailySnapshot)
                    .where(
                        CashDailySnapshot.portfolio_id == cash.portfolio_id,
                        CashDailySnapshot.currency == cash.currency,
                        CashDailySnapshot.snapshot_date
                        >= date(fiscal_year, 10, 1) - timedelta(days=Q4_MAX_GAP_DAYS),
                        CashDailySnapshot.snapshot_date <= year_end,
                    )
                    .order_by(CashDailySnapshot.snapshot_date, CashDailySnapshot.id)
                )
                if snap.balance_native is not None
            ]
            return q4_average_detail(points, fiscal_year)

        # A17 (Nico 30-10-2026): una cuenta con saldo 0 a 31/12 que no entra
        # en el total nunca se omite en silencio: se lista con su nombre y el
        # motivo. Los umbrales del 720 no cambian.
        portfolio_names = {p.id: p.name for p in tenant_portfolios}
        zero_balance_accounts: list[dict] = []

        def _zero_account(cash, reason: str) -> None:
            name = portfolio_names.get(cash.portfolio_id)
            account = f"Cuenta en {cash.currency}" + (f" (cartera «{name}»)" if name else "")
            zero_balance_accounts.append({
                "ticker": f"cash-{cash.currency}",
                "account": account,
                "currency": cash.currency,
                "portfolio_id": cash.portfolio_id,
                "snapshot_date": cash.snapshot_date.isoformat(),
                "reason": reason,
            })

        for cash in cash_rows:
            ticker = f"cash-{cash.currency}"
            # Los saldos NEGATIVOS se NETEAN con los positivos al evaluar el
            # umbral (FAQ AEAT 720): excluirlos inflaría el total.
            if cash.balance_native is None or cash.balance_native == 0:
                # Saldo 0 a 31/12, pero el saldo medio del 4T puede no serlo
                # (p. ej. dólares convertidos a euros en diciembre).
                custody_zero = custody_map.get(f"CASH:{cash.currency}".upper())
                if custody_zero == "ES":
                    _zero_account(cash, (
                        "Saldo 0 a 31/12 y cuenta declarada en España: no es un "
                        "bien en el extranjero, así que no entra en el 720."
                    ))
                    continue
                detail_zero = _q4_native(cash)
                if detail_zero is None:
                    if cash.fx_rate is not None and custody_zero is not None:
                        q4_unknown.append(ticker)
                    _zero_account(cash, (
                        "Saldo 0 a 31/12 y sin capturas suficientes del 4.º "
                        "trimestre para calcular su saldo medio: no se incluye en "
                        "el total de cuentas. El 720 también mira el saldo medio "
                        "del 4.º trimestre; si la cuenta tuvo saldo entre octubre "
                        "y diciembre, compruébalo en los extractos del bróker."
                    ))
                    continue
                if detail_zero["average"] == 0:
                    _zero_account(cash, (
                        "Saldo 0 a 31/12 y saldo medio del 4.º trimestre también "
                        "0: no suma nada al umbral de cuentas, por eso no se incluye "
                        "en el total."
                    ))
                    continue
                # Saldo medio del 4T distinto de 0: nunca se omite en silencio.
                # Mismo trato que un saldo ≠ 0 sin tipo de cambio o sin
                # ubicación declarada: fuera del total y listado para revisar.
                if cash.fx_rate is None:
                    unvalued.append({
                        "ticker": ticker,
                        "snapshot_date": cash.snapshot_date.isoformat(),
                        "reason": (
                            "Saldo 0 a 31/12 pero saldo medio del 4.º trimestre "
                            "distinto de 0, sin tipo de cambio: fuera del total "
                            "EUR, valorar a mano."
                        ),
                    })
                    continue
                avg_zero_base = detail_zero["average"] * Decimal(str(cash.fx_rate))
                if custody_zero is None:
                    foreign_unverified.append({
                        "ticker": ticker,
                        "snapshot_date": cash.snapshot_date.isoformat(),
                        "average_q4_base": _money(avg_zero_base),
                        "reason": (
                            "Saldo 0 a 31/12 pero saldo medio del 4.º trimestre "
                            "distinto de 0 (también cuenta para el umbral). "
                            "Ubicación de la cuenta no declarada (la divisa no es "
                            "el país): declara tax_declarant.custody con la clave "
                            f"'cash:{cash.currency}' en la metadata del tenant; "
                            "mientras tanto, fuera del total."
                        ),
                    })
                    continue
                q4_total += avg_zero_base
                q4_rows += 1
                if detail_zero["estimate"]:
                    q4_estimated.append(ticker)
                continue
            if cuentas_max_date is None or cash.snapshot_date > cuentas_max_date:
                cuentas_max_date = cash.snapshot_date
            if not _price_date_ok(
                ticker,
                cash.snapshot_date,
                cash_price_dates.get((cash.portfolio_snapshot_id, cash.currency)),
                provenance_unproven=cash.portfolio_snapshot_id in cash_unproven,
            ):
                continue
            if cash.fx_rate is None:
                unvalued.append({
                    "ticker": ticker,
                    "snapshot_date": cash.snapshot_date.isoformat(),
                    "reason": "Sin tipo de cambio para el saldo: fuera del total EUR, valorar a mano.",
                })
                continue
            custody = custody_map.get(f"CASH:{cash.currency}".upper())
            if custody is None:
                foreign_unverified.append({
                    "ticker": ticker,
                    "snapshot_date": cash.snapshot_date.isoformat(),
                    "reason": (
                        "Ubicación de la cuenta no declarada (la divisa no es el "
                        "país). Declara tax_declarant.custody con la clave "
                        f"'cash:{cash.currency}' en la metadata del tenant; "
                        "mientras tanto, fuera del total."
                    ),
                })
                continue
            if custody == "ES":
                domestic_assets.append({
                    "ticker": ticker,
                    "value_base": _money(
                        Decimal(str(cash.balance_native)) * Decimal(str(cash.fx_rate))
                    ),
                    "reason": "Cuenta declarada en España: no es bien en el extranjero; no computa en el 720.",
                })
                continue
            amount = Decimal(str(cash.balance_native)) * Decimal(str(cash.fx_rate))
            cuentas_total += amount
            q4_detail = _q4_native(cash)
            avg_base = (
                q4_detail["average"] * Decimal(str(cash.fx_rate))
                if q4_detail is not None
                else None
            )
            if avg_base is None:
                q4_unknown.append(ticker)
            else:
                q4_total += avg_base
                q4_rows += 1
                if q4_detail is not None and q4_detail["estimate"]:
                    q4_estimated.append(ticker)
            cuentas_detail.append({
                "currency": cash.currency,
                "custody_country": custody,
                "snapshot_date": cash.snapshot_date.isoformat(),
                "value_base": _money(amount),
                "average_q4_base": _money(avg_base),
                # True: media estimada arrastrando la última captura a los
                # días sin captura (p. ej. semanales); False: saldo observado
                # los 92 días; None: sin saldo medio.
                "average_q4_estimate": None if q4_detail is None else q4_detail["estimate"],
                "average_q4_observed_days": None if q4_detail is None else q4_detail["observed_days"],
            })

        # Cobertura: una posición/saldo ACTUAL sin ningún snapshot a cierre
        # es invisible para el chequeo si solo miramos snapshots. Listarla
        # como sin valorar: el total nunca la silencia.
        # Cobertura POR CARTERA: un snapshot de AAPL en la cartera A no
        # cubre la posición de AAPL de la cartera B (falso negativo).
        covered_companies = {(p.portfolio_id, p.company_id) for p in positions}
        for position in db.scalars(
            select(Position).where(Position.portfolio_id.in_(portfolio_ids))
        ):
            if (position.portfolio_id, position.company_id) in covered_companies:
                continue
            if not position.quantity or Decimal(str(position.quantity)) == 0:
                continue
            company = db.get(Company, position.company_id)
            ticker = company.ticker if company else f"company-{position.company_id}"
            unvalued.append({
                "ticker": ticker,
                "snapshot_date": None,
                "reason": "Posición actual sin snapshot de valoración a cierre del ejercicio: fuera del total, valorar a mano.",
            })
        covered_currencies = {c.currency for c in cash_rows}
        for balance in db.scalars(
            select(CashBalance).where(CashBalance.tenant_id == portfolio.tenant_id)
        ):
            if balance.currency in covered_currencies:
                continue
            if not balance.balance or Decimal(str(balance.balance)) <= 0:
                continue
            unvalued.append({
                "ticker": f"cash-{balance.currency}",
                "snapshot_date": None,
                "reason": "Saldo actual sin snapshot a cierre del ejercicio: fuera del total, valorar a mano.",
            })

        def _lag(max_date: date | None) -> int | None:
            return None if max_date is None else (year_end - max_date).days

        def _status(
            total: Decimal,
            max_date: date | None,
            *,
            stale: list[dict],
            huecos: bool,
            q4_missing: bool = False,
        ) -> tuple[bool | None, str, list[str]]:
            reasons: list[str] = []
            if stale:
                tickers = ", ".join(sorted({s["ticker"] for s in stale}))
                reasons.append(
                    f"Partidas con snapshot demasiado antiguo ({tickers}): cada "
                    "valor afirma su 31/12 con SU snapshot; uno reciente no "
                    "certifica a otro viejo. Resultado no concluyente."
                )
                return None, "desconocido", reasons
            if max_date is None and total == 0:
                return None, "desconocido", [
                    "Sin snapshots de valoración a cierre del ejercicio: no se puede afirmar nada sobre esta categoría."
                ]
            if total > THRESHOLD_720:
                if huecos:
                    reasons.append(
                        "El total computado supera el umbral, pero hay partidas fuera del cómputo: revisarlas igualmente."
                    )
                return True, "supera", reasons
            if huecos:
                reasons.append(
                    "Hay partidas fuera del total (sin valorar, custodia no verificada o snapshot antiguo): un 'por_debajo' sería falso verde."
                )
                return None, "desconocido", reasons
            if q4_missing:
                reasons.append(
                    "El saldo a 31/12 no supera el umbral, pero falta el "
                    "saldo medio del 4.º trimestre (que también puede "
                    "superarlo): resultado no concluyente."
                )
                return None, "desconocido", reasons
            return False, "por_debajo", reasons

        def _is_cash(t: str) -> bool:
            return t.startswith("cash-")

        stale_v = [s for s in stale_snapshots if not _is_cash(s["ticker"])]
        stale_c = [s for s in stale_snapshots if _is_cash(s["ticker"])]
        huecos_v = stale_v or any(
            not _is_cash(u["ticker"]) for u in unvalued
        ) or any(not _is_cash(f["ticker"]) for f in foreign_unverified)
        huecos_c = stale_c or any(
            _is_cash(u["ticker"]) for u in unvalued
        ) or any(_is_cash(f["ticker"]) for f in foreign_unverified)

        valores_exceeds, valores_status, valores_reasons = _status(
            valores_total, valores_max_date, stale=stale_v, huecos=bool(huecos_v)
        )
        # El umbral de cuentas se supera si lo supera el saldo a 31/12 O el
        # saldo medio del 4T (art. 42 bis.4.b RD 1065/2007): se evalúa el
        # mayor de los dos cuando el saldo medio se conoce para TODAS.
        q4_known = not q4_unknown and (q4_rows > 0 or bool(cuentas_detail))
        cuentas_threshold_total = (
            max(cuentas_total, q4_total) if q4_known else cuentas_total
        )
        cuentas_exceeds, cuentas_status, cuentas_reasons = _status(
            cuentas_threshold_total, cuentas_max_date,
            stale=stale_c, huecos=bool(huecos_c), q4_missing=not q4_known,
        )
        q4_is_estimate = q4_known and bool(q4_estimated)
        if q4_is_estimate:
            cuentas_reasons = cuentas_reasons + [
                "Saldo medio del 4.º trimestre ESTIMADO "
                f"({', '.join(sorted(set(q4_estimated)))}): faltan saldos "
                "diarios y cada día sin captura toma el saldo de la última "
                "captura anterior. No es el saldo medio diario exacto que "
                "pide el modelo; contrastar con el extracto del banco o bróker."
            ]
        if q4_unknown:
            cuentas_reasons = cuentas_reasons + [
                "Sin capturas de saldo suficientes en el 4.º trimestre para "
                f"reconstruir el saldo medio ({', '.join(sorted(set(q4_unknown)))}): "
                "hace falta al menos una por semana del 1/10 al 31/12."
            ]
        if non_eur_portfolios:
            # La mera presencia de carteras no EUR invalida la categoría:
            # posiciones VENDIDAS de esas carteras no dejan fila viva y sin
            # FX oficial a 31/12 no hay conversión fiable. El total mostrado
            # es SOLO la parte EUR, informativo.
            names = ", ".join(
                f"{p.name} ({p.base_currency})" for p in non_eur_portfolios
            )
            valores_exceeds, valores_status = None, "desconocido"
            valores_reasons = valores_reasons + [
                f"Hay carteras con base no EUR ({names}): sus valores "
                "(incluidos los vendidos durante el ejercicio, que ya no "
                "dejan fila) no son convertibles a EUR a 31/12 sin FX "
                "oficial. El total mostrado es solo la parte EUR; la "
                "categoría no es concluyente."
            ]
            cuentas_exceeds, cuentas_status = None, "desconocido"
            cuentas_reasons = cuentas_reasons + [
                f"Hay carteras con base no EUR ({names}): sus saldos no son "
                "convertibles a EUR a 31/12 sin FX oficial. La categoría no "
                "es concluyente."
            ]
        if len(tenant_portfolios) > 1 and cash_rows and cuentas_status != "desconocido":
            # cash_balances no lleva portfolio_id: en multiportfolio los
            # saldos no son atribuibles por cartera y un saldo global único
            # podría contarse dos veces (una captura por cartera).
            cuentas_exceeds, cuentas_status = None, "desconocido"
            cuentas_reasons = cuentas_reasons + [
                "Los saldos de efectivo no son atribuibles por cartera "
                "(cash_balances no registra portfolio_id): con varias "
                "carteras no se puede descartar duplicación de un mismo "
                "saldo global. La categoría no es concluyente."
            ]
        if cuentas_status == "supera":
            # Los saldos importados se agrupan por DIVISA, no por cuenta
            # real: sin identificador de cuenta no se puede validar el neteo
            # ni la ubicación por entidad (FAQ AEAT). Un "supera" construido
            # así sería falsa certeza: queda en no concluyente.
            cuentas_exceeds, cuentas_status = None, "desconocido"
            cuentas_reasons = cuentas_reasons + [
                "El total neto supera el umbral, pero los saldos están "
                "agrupados por divisa y no por cuenta real (identificador de "
                "cuenta y entidad): sin ese dato no se puede validar el "
                "neteo ni la ubicación por entidad. Resultado no concluyente."
            ]

        incomplete = bool(unvalued or foreign_unverified or stale_snapshots)
        base.update({
            "categories": {
                "valores": {
                    "exceeds": valores_exceeds,
                    "status": valores_status,
                    "total_base": _money(valores_total),
                    "positions": sorted(valores_rows, key=lambda r: r["ticker"]),
                    "missing_isin": sorted(missing_isin),
                    "custody": custody_state,
                    "snapshot_lag_days": _lag(valores_max_date),
                    "reasons": valores_reasons,
                },
                "cuentas": {
                    "exceeds": cuentas_exceeds,
                    "status": cuentas_status,
                    "total_base": _money(cuentas_total),
                    "balances": sorted(cuentas_detail, key=lambda r: r["currency"]),
                    "average_q4_missing": not q4_known,
                    "average_q4_total_base": _money(q4_total) if q4_known else None,
                    # Cómo se obtuvo el saldo medio: «saldo_diario_observado»
                    # (captura los 92 días), «estimado_arrastre_capturas»
                    # (días sin captura con el saldo de la anterior) o None.
                    "average_q4_estimate": q4_is_estimate if q4_known else None,
                    "average_q4_method": (
                        None
                        if not q4_known
                        else "estimado_arrastre_capturas"
                        if q4_is_estimate
                        else "saldo_diario_observado"
                    ),
                    "custody": custody_state,
                    "snapshot_lag_days": _lag(cuentas_max_date),
                    "reasons": cuentas_reasons,
                },
                "inmuebles": _inmuebles(),
            },
            "unvalued": unvalued,
            "foreign_unverified": foreign_unverified,
            "short_positions": short_positions,
            "stale_snapshots": stale_snapshots,
            "domestic_assets": domestic_assets,
            "zero_balance_accounts": zero_balance_accounts,
            "incomplete": incomplete,
            "notas": _notas(),
        })
        return base


def _inmuebles() -> dict:
    return {
        "exceeds": None,
        "status": "no_evaluable",
        "total_base": None,
        "note": "No computable con datos de bróker: los inmuebles en el extranjero se declaran aparte. No se afirma ni que superan ni que no superan el umbral.",
    }


def _notas() -> list[str]:
    return [
        "El umbral de 50.000 € se evalúa POR CATEGORÍA (valores, cuentas e "
        "inmuebles por separado), no por el total de la cuenta.",
        "Tri-estado: 'supera' / 'por_debajo' solo con datos suficientes; "
        "'desconocido' cuando falta valoración, cobertura de fechas, base "
        "EUR, saldo medio Q4 o custodia declarada. Un 'desconocido' NO es un 'no'.",
        "Cada partida afirma su valor a 31/12 con SU snapshot: uno reciente "
        "no certifica a otro antiguo (partidas antiguas en 'stale_snapshots').",
        "La custodia se declara POR PARTIDA en tax_declarant.custody "
        "(ISIN/ticker → país, 'cash:<DIVISA>' → país): no se infiere de la "
        "importación ni hay país único para toda la cartera. Custodia 'ES' "
        "no es extranjero y nunca computa.",
        "La obligación nace al EXCEDER 50.000 € por categoría: 50.000 € "
        "exactos no activan el modelo.",
        "Los saldos negativos de cuentas se netean con los positivos al "
        "evaluar el umbral.",
        "La fecha que afirma una valoración es la del precio/saldo EN LA "
        "CAPTURA (provenance del snapshot), no la de las filas vivas ni la "
        "de captura del snapshot.",
        "La obligación es por declarante: se agregan todas las carteras "
        "del tenant. Los saldos de efectivo no son atribuibles por cartera "
        "(limitación del esquema): en multiportfolio la categoría de "
        "cuentas queda no concluyente.",
        "El umbral se evalúa en EUR: con divisa base distinta de EUR la "
        "categoría queda 'desconocido' (sin conversión oficial a 31/12).",
        "Cuentas: el umbral se evalúa con el mayor entre el saldo a 31/12 y "
        "el saldo medio del 4.º trimestre (ambos al tipo de cambio del 31/12). "
        "Si faltan capturas semanales de caja en el 4T, el saldo medio no se "
        "calcula (average_q4_missing) y el resultado no es concluyente. "
        "Con capturas no diarias el saldo medio es una estimación "
        "(average_q4_estimate / average_q4_method), no el saldo medio diario exacto.",
        "Chequeo orientativo: la obligación real depende también de "
        "titularidad, cotitulares y variaciones del año; contrastar "
        "con los extractos del bróker.",
    ]
