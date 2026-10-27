"""Pruebas diferenciales del motor fiscal contra una referencia independiente.

La referencia (`ref_replay`) esta escrita desde la especificacion documentada
(docstring de ``tax_report_service`` + Manual Renta 2025, cap. 11, apdo. E:
FIFO art. 37.2 LIRPF, recompra de valores homogeneos en 2 meses con
proporcionalidad y excepcion de compra unica) con aritmetica exacta
(``Fraction``) y estructura deliberadamente distinta a la implementacion
bajo prueba. Los escenarios son sinteticos con semilla fija: clusters
adversariales de wash-sale (recompras cruzadas, sobreventas, fracciones,
operaciones el mismo dia, huecos de FX > 7 dias, divisas EUR/USD/GBP/JPY).

Nunca se afirma un criterio fiscal discutido: donde el motor documenta una
interpretacion (conversion unica de la ganancia al cambio de venta),
la referencia implementa la MISMA convencion para que la prueba detecte
desviaciones de implementacion, no de criterio.

El volumen de escenarios se amplia con la variable de entorno
``FISCAL_DIFF_SCALE`` (workflow nocturno ``fiscal-differential.yml``).
"""

from __future__ import annotations

import os
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction as F
from types import SimpleNamespace

import pytest
from dateutil.relativedelta import relativedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FXRate, Portfolio, Transaction
from app.services.tax_report_service import (
    TaxReportService,
    _fifo_sort_key,
    replay_tax_fifo,
)

D = Decimal
WASH = relativedelta(months=2)
BUYS = {"buy", "bot", "b"}
SELLS = {"sell", "sold"}
SCALE = int(os.environ.get("FISCAL_DIFF_SCALE", "1"))


# --------------------------------------------------------------------------
# Referencia independiente (espec -> Fraction, estructura propia)
# --------------------------------------------------------------------------


def _f(v):
    return None if v is None else F(str(v))


class _Lot:
    __slots__ = ("qty", "unit", "unit_base", "deferred", "deferred_base", "capacity", "date")

    def __init__(self, qty, unit, unit_base, when):
        self.qty = qty
        self.unit = unit
        self.unit_base = unit_base
        self.deferred = F(0)
        self.deferred_base = F(0) if unit_base is not None else None
        self.capacity = qty
        self.date = when


def ref_replay(events, resolve_rate, start, end):
    lots: list[_Lot] = []
    open_losses: list[dict] = []
    year_sales: list[dict] = []
    hist_buys: list[tuple] = []
    hist_sells: list[tuple] = []
    for tx in events:
        action = (tx.action or "").lower()
        if action in BUYS:
            q = _f(tx.quantity)
            if q is None or q <= 0:
                continue
            unit = (q * _f(tx.price) + (_f(tx.fees) or F(0))) / q
            r = _f(resolve_rate(tx.currency, tx.trade_date))
            lot = _Lot(q, unit, unit * r if r is not None else None, tx.trade_date)
            still = []
            for s in open_losses:
                if tx.trade_date > s["date"] + WASH:
                    continue
                if s["qty_unblocked"] > 0 and lot.capacity > 0:
                    take = min(lot.capacity, s["qty_unblocked"])
                    lot.deferred += take * s["lps"]
                    if lot.deferred_base is not None:
                        lot.deferred_base = (
                            None if s["lps_base"] is None else lot.deferred_base + take * s["lps_base"]
                        )
                    lot.capacity -= take
                    s["blocked"] += take
                    s["qty_unblocked"] -= take
                still.append(s)
            open_losses = still
            lots.append(lot)
            hist_buys.append((tx.trade_date, q))
            continue
        if action not in SELLS:
            continue
        q = _f(tx.quantity)
        if q is None or q <= 0:
            continue
        proceeds = q * _f(tx.price) - (_f(tx.fees) or F(0))
        remaining = q
        cost = F(0)
        cost_base: F | None = F(0)
        li = 0
        while remaining > 0 and li < len(lots):
            lot = lots[li]
            take = min(lot.qty, remaining)
            cost += take * lot.unit
            if cost_base is not None and lot.unit_base is not None:
                cost_base += take * lot.unit_base
            else:
                cost_base = None
            if lot.qty > 0 and lot.deferred_base is None:
                cost_base = None
            elif lot.deferred_base is not None and lot.deferred_base > 0 and lot.qty > 0:
                dtb = lot.deferred_base * take / lot.qty
                if cost_base is not None:
                    cost_base += dtb
                lot.deferred_base -= dtb
            if lot.deferred > 0 and lot.qty > 0:
                dt = lot.deferred * take / lot.qty
                cost += dt
                lot.deferred -= dt
            lot.qty -= take
            remaining -= take
            if lot.qty == 0:
                li += 1
        del lots[:li]
        over_qty = remaining if remaining > 0 else F(0)
        gain = proceeds - cost
        r = _f(resolve_rate(tx.currency, tx.trade_date))
        proceeds_base = proceeds * r if r is not None else None
        cost_base = cost * r if r is not None else None
        gain_base = gain * r if r is not None else None
        hist_sells.append((tx.trade_date, q))
        is_loss = gain_base < 0 if gain_base is not None else gain < 0
        sale = None
        if is_loss:
            sale = {
                "date": tx.trade_date,
                "qty_unblocked": q,
                "lps": max(-gain, F(0)) / q,
                "lps_base": (max(-gain_base, F(0)) / q if gain_base is not None else None),
                "blocked": F(0),
            }
            wstart = tx.trade_date - WASH
            buys_w = [(d, qq) for d, qq in hist_buys if wstart <= d <= tx.trade_date]
            holdings_before = max(
                sum((qq for d, qq in hist_buys if d < wstart), F(0))
                - sum((qq for d, qq in hist_sells if d < wstart), F(0)),
                F(0),
            )
            if len(buys_w) == 1 and holdings_before <= 0:
                recompra = F(0)
            else:
                eligible = sum(
                    (min(l.qty, l.capacity) for l in lots if wstart <= l.date <= tx.trade_date),
                    F(0),
                )
                recompra = min(q, eligible, sum((qq for _, qq in buys_w), F(0)))
            to_block = recompra
            for lot in lots:
                if to_block <= 0 or sale["qty_unblocked"] <= 0:
                    break
                if lot.date < wstart or lot.capacity <= 0 or lot.qty <= 0:
                    continue
                take = min(lot.capacity, lot.qty, to_block, sale["qty_unblocked"])
                lot.deferred += take * sale["lps"]
                if lot.deferred_base is not None:
                    lot.deferred_base = (
                        None if sale["lps_base"] is None else lot.deferred_base + take * sale["lps_base"]
                    )
                lot.capacity -= take
                sale["blocked"] += take
                sale["qty_unblocked"] -= take
                to_block -= take
            open_losses.append(sale)
        if start <= tx.trade_date <= end:
            year_sales.append(
                {
                    "tx": tx,
                    "proceeds": proceeds,
                    "cost": cost,
                    "gain": gain,
                    "proceeds_base": proceeds_base,
                    "cost_base": cost_base,
                    "gain_base": gain_base,
                    "sale": sale,
                    "over_sell": over_qty > 0,
                }
            )
    return lots, year_sales


# --------------------------------------------------------------------------
# Generadores sinteticos
# --------------------------------------------------------------------------


def _tx(i, action, qty, price, fees, currency, day, with_time=False, rng=None):
    payload = {}
    if with_time and rng is not None:
        payload = {"dateTime": f"{day:%Y%m%d};{rng.randint(0, 235959):06d}"}
    return SimpleNamespace(
        id=i, action=action, quantity=qty, price=price, fees=fees,
        currency=currency, trade_date=day, raw_payload=payload,
    )


def _gen_rates(rng, currency, d0, d1, holes):
    rate = {"USD": D("1.10"), "GBP": D("0.85"), "JPY": D("0.0061")}.get(currency, D("1.3"))
    series = {}
    day = d0
    while day <= d1:
        if day.weekday() < 5:
            series[day] = rate
        rate *= D(1) + D(rng.uniform(-0.003, 0.003)).quantize(D("0.000001"))
        day += timedelta(days=1)
    if holes:
        for _ in range(2):
            hole = d0 + timedelta(days=rng.randint(0, max(1, (d1 - d0).days - 20)))
            for k in range(rng.randint(9, 15)):
                series.pop(hole + timedelta(days=k), None)
    return series


def _make_resolve(series_by_currency):
    def resolve(currency, as_of):
        if currency == "EUR":
            return D(1)
        series = series_by_currency.get(currency)
        if not series:
            return None
        cand = [d for d in series if d <= as_of]
        if not cand:
            return None
        dd = max(cand)
        if (as_of - dd).days > 7:
            return None
        return series[dd]

    return resolve


def _gen_cluster_events(rng, d0, currency):
    events = []
    day = d0
    holdings = D(0)
    price = D(rng.uniform(20, 200)).quantize(D("0.01"))
    for i in range(1, rng.randint(5, 45) + 1):
        day = day + timedelta(days=rng.choice([0, 0, 1, 1, 2, 3, 7, 15, 40, 70, 200]))
        price = max(D("0.5"), (price * (1 + D(str(round(rng.uniform(-0.25, 0.22), 3))))).quantize(D("0.01")))
        r = rng.random()
        if holdings <= 0 or r < 0.5:
            qty = D(rng.choice([1, 2, 5, 10, 33, 100]))
            if rng.random() < 0.15:
                qty = (qty / D(3)).quantize(D("0.0001"))
            if rng.random() < 0.03:
                qty = rng.choice([None, D(0), D(-3)])
            else:
                holdings += qty
            fees = D(rng.uniform(0, 4)).quantize(D("0.01")) if rng.random() < 0.5 else D(0)
            events.append(_tx(i, "buy", qty, price, fees, currency, day, rng.random() < 0.5, rng))
        else:
            frac = rng.random()
            if frac < 0.06:
                qty = holdings + D(rng.randint(1, 10))
            elif frac < 0.4:
                qty = holdings
            else:
                qty = max(D("0.0001"), (holdings * D(rng.uniform(0.05, 0.9))).quantize(D("0.0001")))
            if rng.random() < 0.03:
                qty = rng.choice([None, D(0)])
            else:
                holdings -= qty
            fees = D(rng.uniform(0, 4)).quantize(D("0.01")) if rng.random() < 0.5 else D(0)
            events.append(_tx(i, "sell", qty, price, fees, currency, day, rng.random() < 0.5, rng))
    events.sort(key=_fifo_sort_key)
    return events, day


def _close(a, b, tol=F(1, 10**6)):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol * max(F(1), abs(a), abs(b))


def _compare_replay(events, resolve, start, end, full_window):
    lots_e, sales_e = replay_tax_fifo(list(events), resolve, start, end)
    lots_r, sales_r = ref_replay(list(events), resolve, start, end)
    errs = []
    assert len(sales_e) == len(sales_r), "divergencia estructural en nº de ventas"
    for k, (se, sr) in enumerate(zip(sales_e, sales_r)):
        for fe, fr in (
            ("proceeds_native", "proceeds"), ("cost_native", "cost"),
            ("gain_native", "gain"), ("proceeds_base", "proceeds_base"),
            ("cost_base", "cost_base"), ("gain_base_raw", "gain_base"),
        ):
            if not _close(_f(se[fe]), _f(sr[fr])):
                errs.append(f"venta {k} {fe}: motor={se[fe]} ref={sr[fr]}")
        be = se["sale"]["blocked_qty"] if se["sale"] else D(0)
        br = sr["sale"]["blocked"] if sr["sale"] else F(0)
        if not _close(_f(be), _f(br)):
            errs.append(f"venta {k} bloqueado: motor={be} ref={br}")
        if bool(se["over_sell"]) != bool(sr["over_sell"]):
            errs.append(f"venta {k} over_sell: motor={se['over_sell']} ref={sr['over_sell']}")
    le, lr = list(lots_e), lots_r
    if len(le) != len(lr):
        errs.append(f"nº lotes {len(le)} vs {len(lr)}")
    for k, (ae, ar) in enumerate(zip(le, lr)):
        for fe, fr in (("qty", "qty"), ("deferred", "deferred"),
                       ("deferred_base", "deferred_base"), ("capacity", "capacity")):
            if not _close(_f(ae[fe]), _f(getattr(ar, fr))):
                errs.append(f"lote {k} {fe}: motor={ae[fe]} ref={getattr(ar, fr)}")
        for campo in ("qty", "capacity", "deferred"):
            if _f(ae[campo]) is not None and _f(ae[campo]) < 0:
                errs.append(f"lote {k} {campo} negativo: {ae[campo]}")
    if full_window:
        tot_buy = sum(
            (_f(t.quantity) * _f(t.price) + (_f(t.fees) or F(0)))
            for t in events
            if (t.action or "").lower() in BUYS and t.quantity is not None and t.quantity > 0
        )
        consumed = sum((_f(s["cost_native"]) for s in sales_e), F(0))
        alive_basis = sum((_f(l["qty"]) * _f(l["unit"]) for l in le), F(0))
        d_abs = sum(
            (_f(s["sale"]["blocked_qty"]) * _f(s["sale"]["loss_per_share"])
             for s in sales_e if s["sale"]),
            F(0),
        )
        d_alive = sum((_f(l["deferred"]) for l in le), F(0))
        rhs = consumed + alive_basis - (d_abs - d_alive)
        if not _close(tot_buy, rhs, tol=F(1, 10**4)):
            errs.append(
                f"conservacion de base: compras={float(tot_buy):.4f} "
                f"consumido+vivo-diferidos={float(rhs):.4f}"
            )
    return errs


@pytest.mark.parametrize("seed", range(60 * SCALE))
def test_replay_fifo_diferencial_clusters_wash_sale(seed):
    rng = random.Random(10000 + seed)
    cur = rng.choice(["EUR", "USD", "USD", "GBP", "JPY"])
    d0 = date(2023, 1, 1) + timedelta(days=rng.randint(0, 300))
    events, d_last = _gen_cluster_events(rng, d0, cur)
    series = _gen_rates(rng, cur, date(2022, 12, 1), d_last + timedelta(days=10), rng.random() < 0.4)
    resolve = _make_resolve({cur: series})
    if rng.random() < 0.5:
        ys, ye = date(2022, 1, 1), date(2026, 12, 31)
    else:
        y = rng.choice([2023, 2024, 2025, 2026])
        ys, ye = date(y, 1, 1), date(y, 12, 31)
    errs = _compare_replay(events, resolve, ys, ye, full_window=(ys <= d0 and ye >= d_last))
    assert not errs, f"seed {seed} divisa {cur}: " + "; ".join(errs[:6])


# --------------------------------------------------------------------------
# Pila completa: compute_report sobre sqlite en memoria vs referencia
# --------------------------------------------------------------------------


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _money_f(x):
    if x is None:
        return None
    q = D(x.numerator) / D(x.denominator) if isinstance(x, F) else x
    return F(str(q.quantize(D("0.01"), rounding=ROUND_HALF_UP)))


@pytest.mark.parametrize("seed", range(12 * SCALE))
def test_compute_report_diferencial_pila_completa(db, seed):
    rng = random.Random(50000 + seed)
    d0, d1 = date(2023, 1, 1), date(2025, 12, 31)
    year = rng.choice([2023, 2024, 2025])
    tickers = {f"TK{k}": rng.choice(["EUR", "USD", "USD", "GBP"]) for k in range(rng.randint(1, 3))}
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    companies = {}
    for tk, cur in tickers.items():
        c = Company(
            ticker=tk, name=tk, exchange="X", currency=cur, sector="S", industry="I",
            company_type="holding", valuation_model="unassigned",
            special_sources=[], special_risks=[], factor_tags=[],
        )
        db.add(c)
        companies[tk] = c
    db.flush()
    series_by_currency = {}
    for cur in set(tickers.values()) - {"EUR"}:
        series = _gen_rates(rng, cur, d0 - timedelta(days=400), d1 + timedelta(days=30), rng.random() < 0.4)
        for day, r in series.items():
            db.add(FXRate(base_currency="EUR", quote_currency=cur, rate_date=day, rate=r, source="test"))
        series_by_currency[cur] = series
    db.commit()
    txs = []
    i = 0
    for tk, company in companies.items():
        cur = tickers[tk]
        holdings = D(0)
        price = D(rng.uniform(10, 300)).quantize(D("0.01"))
        for _ in range(rng.randint(2, 25)):
            i += 1
            day = d0 + timedelta(days=rng.randint(0, (d1 - d0).days))
            r = rng.random()
            if r < 0.45 or holdings <= 0:
                qty = D(rng.choice([1, 2, 5, 10, 25, 100]))
                if rng.random() < 0.1:
                    qty = (qty / D(4)).quantize(D("0.0001"))
                fees = D(rng.uniform(0, 5)).quantize(D("0.01")) if rng.random() < 0.5 else D(0)
                holdings += qty
                txs.append(Transaction(company_id=company.id, trade_date=day, action="buy",
                                       quantity=qty, price=price, fees=fees, currency=cur))
            elif r < 0.8:
                if rng.random() < 0.06:
                    qty = holdings + D(rng.randint(1, 20))
                elif rng.random() < 0.5:
                    qty = holdings
                else:
                    qty = max(D("0.0001"), (holdings * D(rng.uniform(0.1, 0.9))).quantize(D("0.0001")))
                fees = D(rng.uniform(0, 5)).quantize(D("0.01")) if rng.random() < 0.5 else D(0)
                holdings -= qty
                txs.append(Transaction(company_id=company.id, trade_date=day, action="sell",
                                       quantity=qty, price=price, fees=fees, currency=cur))
            elif r < 0.9:
                amount = D(rng.uniform(1, 400)).quantize(D("0.01"))
                qty = D(1) if rng.random() > 0.05 else D("2.5")
                payload = {"type": "Payment In Lieu Of Dividends", "trxID": str(i)} if rng.random() < 0.08 else {}
                txs.append(Transaction(company_id=company.id, trade_date=day, action="dividend",
                                       quantity=qty, price=amount, fees=D(0), currency=cur,
                                       raw_payload=payload))
            else:
                amount = D(rng.uniform(0.5, 60)).quantize(D("0.01"))
                txs.append(Transaction(company_id=company.id, trade_date=day, action="withholding",
                                       quantity=D(1), price=-amount, fees=D(0), currency=cur,
                                       raw_payload={"type": "Withholding Tax", "trxID": str(i)}))
    for _ in range(rng.randint(0, 3)):
        i += 1
        day = d0 + timedelta(days=rng.randint(0, (d1 - d0).days))
        cur = rng.choice(list(set(tickers.values())))
        txs.append(Transaction(company_id=None, trade_date=day, action="dividend",
                               quantity=D(1), price=D(rng.uniform(1, 200)).quantize(D("0.01")),
                               fees=D(0), currency=cur,
                               raw_payload={"type": "Dividends", "symbol": "ORPH"}))
    db.add_all(txs)
    db.commit()

    report = TaxReportService().compute_report(db, year, include_filing=False)

    # Referencia: mismos eventos leidos de la BD, mismas convenciones.
    start, end = date(year, 1, 1), date(year, 12, 31)
    resolve = _make_resolve(series_by_currency)
    ref_realized = {}
    for tk, company in companies.items():
        evs = [
            SimpleNamespace(
                id=t.id, action=t.action, quantity=t.quantity, price=t.price,
                fees=t.fees, currency=t.currency, trade_date=t.trade_date,
                raw_payload=t.raw_payload or {},
            )
            for t in txs
            if t.company_id == company.id and (t.action or "").lower() in BUYS | SELLS
        ]
        evs.sort(key=_fifo_sort_key)
        _, year_sales = ref_replay(evs, resolve, start, end)
        if not year_sales:
            continue
        b = {"cost_native": F(0), "gain_native": F(0), "gain_base": F(0),
             "blocked_base": F(0), "missing_fx": False, "over_sell": False}
        for e in year_sales:
            sale = e["sale"]
            blocked_n = sale["blocked"] * sale["lps"] if sale else F(0)
            gb = e["gain_base"]
            if gb is not None and (sale is None or sale["lps_base"] is not None):
                computable_b = gb + (sale["blocked"] * sale["lps_base"] if sale else F(0))
            else:
                computable_b = None
                b["missing_fx"] = True
            b["cost_native"] += e["cost"]
            b["gain_native"] += e["gain"] + blocked_n
            if computable_b is not None:
                b["gain_base"] += computable_b
                if sale:
                    b["blocked_base"] += sale["blocked"] * sale["lps_base"]
            if e["over_sell"]:
                b["over_sell"] = True
        ref_realized[tk] = {
            "cost_native": None if b["over_sell"] else _money_f(b["cost_native"]),
            "gain_native": None if b["over_sell"] else _money_f(b["gain_native"]),
            "gain_base": None if (b["missing_fx"] or b["over_sell"]) else _money_f(b["gain_base"]),
            "blocked_loss_base": None if b["missing_fx"] else _money_f(b["blocked_base"]),
        }

    eng = {r["ticker"]: r for r in report["realized"]}
    errs = []
    for tk, ref_b in ref_realized.items():
        eb = eng.get(tk)
        if eb is None:
            errs.append(f"{tk}: falta bucket en el informe")
            continue
        for field in ("cost_native", "gain_native", "gain_base", "blocked_loss_base"):
            rv = ref_b[field]
            evv = eb[field]
            evf = F(str(evv)) if evv is not None else None
            if (rv is None) != (evf is None):
                errs.append(f"{tk}.{field}: motor={evv} ref={rv}")
            elif rv is not None and abs(rv - evf) > F(1, 100):
                errs.append(f"{tk}.{field}: motor={evv} ref={float(rv):.4f}")
    assert not errs, f"seed {seed}: " + "; ".join(errs[:6])
