"""Nota de 0 a 10 por tesis y analistas frente a nosotros (sin UI).

Subcomandos (todos escriben en --out):
  collect         rigor determinista (arnés de expertos), valor por acción, método, consenso de analistas
                  (Yahoo, gratuito) y el texto de cada tesis para el juez. Sin modelo.
  judge           juez ciego con rúbrica fija, en las dos órdenes, frente a un ancla (informe de Numantia;
                  el de la misma empresa cuando existe) y un placebo (la misma tesis en A y B). Proveedor de la app.
  score           nota por tesis con sus componentes → notas.json y notas.md.
  forecast-log    registro con fecha: nuestro valor bajista/base/alcista y el objetivo de analistas.
  forecast-score  puntúa ese registro a 1 o 3 años contra el precio real (cuando llegue la fecha).

Nunca se puntúa la prosa contra rentabilidades pasadas: el modelo ya sabe lo que pasó (look-ahead).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services import nota_tesis as nt  # noqa: E402

TICKERS = [
    "ASTS",
    "CGEO.L",
    "CPT",
    "BN",
    "KKR",
    "POOL",
    "CB",
    "UNH",
    "HIMS",
    "RXRX",
    "NAUT",
    "ABCL",
    "IBRX",
    "AAPL",
    "ERF.PA",
    "GOOGL",
    "TSM",
    "AIR.PA",
    "META",
    "AMZN",
    "TSLA",
    "FRPH",
    "CNQ",
    "FFH.TO",
]


def _rows(db):
    from sqlalchemy import select

    from app.models.declared_input_value import DeclaredInputValue
    from app.models.entities import Company

    return {
        t: row
        for t, row in db.execute(
            select(Company.ticker, DeclaredInputValue)
            .join(Company, Company.id == DeclaredInputValue.company_id)
            .where(DeclaredInputValue.input_key == "thesis_v2", DeclaredInputValue.superseded_at.is_(None))
        ).all()
    }


def _n_analysts(symbol: str) -> int | None:
    """Número de analistas que declara Yahoo (misma fuente gratuita que los objetivos); None si no lo da."""
    try:
        import yfinance as yf

        n = (yf.Ticker(symbol).get_info() or {}).get("numberOfAnalystOpinions")
        return int(n) if n else None
    except Exception:  # noqa: BLE001 - dato accesorio
        return None


async def _consensus(symbol: str) -> dict[str, Any]:
    from app.services.analyst_targets_service import analyst_targets_service

    try:
        r = (await analyst_targets_service.get(symbol)).model_dump()
    except Exception as exc:  # noqa: BLE001
        return {"status": "fetch_failed", "error": type(exc).__name__}
    c = r.get("consensus") or {}
    firms = {x["firm"] for x in r.get("rows") or []}
    return {
        "status": "available"
        if c.get("mean")
        else ("empty" if r.get("status") != "unavailable" else "fetch_failed"),
        "mean": c.get("mean"),
        "median": c.get("median"),
        "low": c.get("low"),
        "high": c.get("high"),
        "currency": r.get("currency"),
        "reference_price": r.get("reference_price"),
        "n_firms_12m": len(firms),
        "n_analysts": _n_analysts(symbol),
        "source": r.get("source"),
        "source_url": r.get("source_url"),
        "fetched_at": r.get("fetched_at"),
    }


def _convert(db, rec: dict[str, Any], day: date) -> None:
    """Consenso en otra divisa que la nuestra: se convierte con los tipos guardados (BCE) y se anota cómo."""
    from app.services.user_sotp_service import convert_amount

    cons, ours = rec.get("consensus") or {}, (rec.get("currency") or "").upper()
    one, theirs = nt.to_major(1.0, cons.get("currency"))
    if not ours or not theirs or ours == theirs or cons.get("status") != "available":
        return
    try:
        conv = convert_amount(db, one or 1.0, theirs, ours, day)
    except Exception:  # noqa: BLE001 - sin tipo: queda «divisas distintas»
        conv = None
    if not conv:
        return
    rate = conv[0] / (one or 1.0)
    cons["converted"] = {
        **{
            k: (
                None
                if cons.get(k) is None
                else (nt.to_major(float(cons[k]), cons.get("currency"))[0] or 0.0) * rate
            )
            for k in ("mean", "median", "low", "high")
        },
        "currency": ours,
        "status": "available",
        "fx": conv[1],
    }


def cmd_collect(args) -> None:
    import expert_bench as xb  # scripts/expert_bench.py

    from app.core.database import SessionLocal
    from app.services.expert_team.thesis_v2 import build_context, render

    out = Path(args.out)
    (out / "texts").mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    rows = _rows(db)
    res = []
    for t in args.tickers.split(","):
        rec: dict[str, Any] = {"ticker": t}
        row = rows.get(t)
        company = xb._company(db, t)
        try:
            if company is not None:
                ctx = build_context(db, company, today=date.fromisoformat(args.as_of), tenant_id=1)
                v = ctx.valuation
                sp = v.get("starting_point") or {}
                rec.update(
                    valuation_status=v.get("status"),
                    method=(v.get("method") or {}).get("chosen"),
                    kind=(v.get("method") or {}).get("kind"),
                    price=sp.get("price"),
                    currency=sp.get("currency"),
                    basis=sp.get("basis"),
                    multiple=sp.get("multiple"),
                    value_per_share=v.get("value_per_share") or {},
                    irr5={
                        k: (
                            (((v.get("scenarios") or {}).get(k) or {}).get("horizons") or {}).get("5") or {}
                        ).get("irr")
                        for k in ("bear", "base", "bull")
                    },
                    base_drivers=(((v.get("scenarios") or {}).get("base") or {}).get("drivers")),
                    valuation_fingerprint=v.get("fingerprint"),
                    discount_rate=v.get("discount_rate"),
                    discount_rate_source=v.get("discount_rate_source"),
                    cash_conversion=(((v.get("scenarios") or {}).get("base") or {}).get("drivers") or {}).get(
                        "cash_conversion"
                    ),
                )
            if row is not None:
                doc = (row.metadata_ or {}).get("thesis") or {}
                markers = dict((row.metadata_ or {}).get("markers") or {})
                rec["thesis"] = {
                    "status": doc.get("status"),
                    "fingerprint": doc.get("fingerprint"),
                    "created_at": str(row.created_at),
                    "valuation_fingerprint": (row.metadata_ or {}).get("valuation_fingerprint"),
                }
                rec["thesis"]["desfasada"] = rec["thesis"]["valuation_fingerprint"] not in (
                    None,
                    rec.get("valuation_fingerprint"),
                )
                rec["rigor"] = xb.rigor_for(
                    db, t, doc, today=row.as_of or date.today(), stored_markers=markers
                )
                if company is not None:  # baremo v2: kill switches comprobables (valor actual calculado)
                    rec["rigor"]["kill_switches_v2"] = nt.kill_switch_report_v2(ctx.switches)
                text = "\n\n".join(render(doc.get("sections") or {}, markers).values())
                (out / "texts" / f"{t}.txt").write_text(text)
        except Exception as exc:  # noqa: BLE001 - se anota y se sigue
            rec["error"] = f"{type(exc).__name__}: {exc}"[:300]
        db.rollback()
        rec["consensus"] = asyncio.run(_consensus(t)) if not args.no_consensus else None
        _convert(db, rec, date.fromisoformat(args.as_of))
        res.append(rec)
        print(
            "collect",
            t,
            rec.get("valuation_status"),
            (rec.get("thesis") or {}).get("status"),
            (rec.get("consensus") or {}).get("status"),
            flush=True,
        )
    (out / "collect.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))


# ------------------------------------------------------------------------------------------------ juez


def _spent(out: Path) -> float:
    f = out / "calls.jsonl"
    if not f.exists():
        return 0.0
    return sum(json.loads(x).get("cost_eur") or 0 for x in f.read_text().splitlines() if x.strip())


async def _judge(args) -> None:
    import expert_bench as xb

    from app.services.expert_team.service import provider_reasoner

    out = Path(args.out)
    jdir = out / "judge"
    jdir.mkdir(parents=True, exist_ok=True)
    before = _spent(out)
    meter = xb._provider(max(0.0, args.cap_eur - before), out)
    anchors = dict(a.split("=", 1) for a in args.anchors.split(","))  # TICKER=ruta; «*» = ancla común
    collect = {r["ticker"]: r for r in json.loads((out / "collect.json").read_text())}
    sem = asyncio.Semaphore(args.parallel)
    reasoner = provider_reasoner(meter, db=None, temperature=0.0)

    async def pair(tag: str, x: str, y: str) -> None:
        path = jdir / f"{tag}.json"
        if path.exists():
            return
        verdicts = []
        async with sem:
            for a, b in ((x, y), (y, x)):
                if meter.stopped:
                    print("STOP", meter.stopped, flush=True)
                    return
                try:
                    text = await reasoner(nt.JUEZ_RUBRICA, nt.judge_message(a, b), 8000, "nota_tesis.juez")
                except xb.Stop as exc:
                    print("STOP", tag, exc, flush=True)
                    return
                except Exception as exc:  # noqa: BLE001 - sin reintento
                    print("judge error", tag, type(exc).__name__, flush=True)
                    text = ""
                verdicts.append(xb.eb.parse_judge(text))
        doc = {
            "tag": tag,
            "first": verdicts[0],
            "swapped": verdicts[1],
            "result": nt.judge_result(verdicts[0], verdicts[1]),
        }
        path.write_text(json.dumps(doc, ensure_ascii=False))
        print("judge", tag, doc["result"], f"{before + meter.spent:.3f}€", flush=True)

    jobs = []
    for t, rec in collect.items():
        tf = out / "texts" / f"{t}.txt"
        if not tf.exists():
            continue
        fp = ((rec.get("thesis") or {}).get("fingerprint") or "x")[:12]
        ref = anchors.get(t) or anchors.get("*")
        if not ref:
            continue
        ref_name = "misma" if t in anchors else "comun"
        text = tf.read_text()
        jobs.append(pair(f"{t}__{fp}__{ref_name}", text, Path(ref).read_text()))
    for t in [x for x in args.placebo.split(",") if x]:
        tf = out / "texts" / f"{t}.txt"
        if tf.exists():
            text = tf.read_text()
            fp = ((collect.get(t, {}).get("thesis") or {}).get("fingerprint") or "x")[:12]
            jobs.append(pair(f"placebo__{t}__{fp}", text, text))
    await asyncio.gather(*jobs)
    print("JUDGE DONE", f"{before + meter.spent:.3f}€", meter.stopped, flush=True)


# ------------------------------------------------------------------------------------------------ nota


def _judge_for(out: Path, t: str, fp: str | None) -> dict[str, Any] | None:
    for name in ("misma", "comun"):
        f = out / "judge" / f"{t}__{(fp or 'x')[:12]}__{name}.json"
        if f.exists():
            d = json.loads(f.read_text())
            return {
                **d["result"],
                "ancla": "Numantia misma empresa" if name == "misma" else "Numantia (otra empresa)",
            }
    return None


def _score_v2(
    rec: dict[str, Any], flags: list, primary: dict[str, Any], j: dict[str, Any] | None
) -> dict[str, Any]:
    """Baremo estricto v2 (congelado) sobre la misma recogida que v1."""
    t = rec["ticker"]
    prim = primary.get(t) or primary.get(t.split(".")[0]) or {}
    rig = rec["rigor"]
    sh = _num(((rig.get("source") or {}).get("shares") or {}).get("value"))
    mcap = (sh or 0) * float(rec.get("price") or 0) or None
    rc = nt.rigor_components_v2(rig, flags, prim, rig.get("kill_switches_v2"), mcap)
    jz = nt.judge_vs_numantia_10((j or {}).get("delta_vs_ancla"), (j or {}).get("nota_5"))
    return {"rigor": rc, "juez_10": jz, **nt.grade_v2(rc["rigor_10"], jz)}


def _num(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def cmd_score(args) -> None:
    out = Path(args.out)
    audit = json.loads(Path(args.audit).read_text())
    primary = json.loads(Path(args.primary).read_text()) if args.primary else {}
    collect = json.loads((out / "collect.json").read_text())
    placebo = [json.loads(f.read_text()) for f in sorted((out / "judge").glob("placebo__*.json"))]
    res = []
    for rec in collect:
        t = rec["ticker"]
        flags = audit.get(t) or audit.get(t.split(".")[0]) or []
        r: dict[str, Any] = {
            "ticker": t,
            "provisional": args.provisional,
            "thesis_status": (rec.get("thesis") or {}).get("status"),
            "desfasada": (rec.get("thesis") or {}).get("desfasada"),
        }
        if rec.get("rigor") and t in nt.REFERENCIA_CORREGIDA:
            import expert_bench as xb

            ref, why = nt.REFERENCIA_CORREGIDA[t]
            m = rec["rigor"].get("method") or {}
            tf = out / "texts" / f"{t}.txt"
            rec["rigor"]["method"] = {
                **xb.eb.method_fit(
                    ref, m.get("chosen"), tf.read_text() if tf.exists() else "", m.get("kind")
                ),
                "referencia_corregida": f"{m.get('type')} → {ref}: {why}",
            }
        if rec.get("rigor") and not rec["rigor"].get("error"):
            rc = nt.rigor_components(rec["rigor"], flags)
            j = _judge_for(out, t, (rec.get("thesis") or {}).get("fingerprint"))
            g = nt.grade(rc["rigor_10"], (j or {}).get("nota_5"))
            r.update(rigor=rc, juez=j, **g)
            r["v2"] = _score_v2(rec, flags, primary, j)
        else:
            r.update(nota=None, formula="sin tesis v2 guardada: sin nota")
            r["v2"] = nt.grade_v2(None, None)
        cons = rec.get("consensus") or {}
        r["analistas"] = nt.analyst_gap(
            rec.get("value_per_share") or {}, rec.get("currency"), cons.get("converted") or cons
        )
        if cons.get("converted"):
            r["analistas"]["fx"] = cons["converted"]["fx"]
        r["n_analistas"] = (rec.get("consensus") or {}).get("n_analysts")
        r["n_firmas_12m"] = (rec.get("consensus") or {}).get("n_firms_12m")
        r["fuente_analistas"] = (rec.get("consensus") or {}).get("source_url")
        r["valor"] = rec.get("value_per_share")
        r["precio"] = rec.get("price")
        r["divisa"] = rec.get("currency")
        r["metodo"] = rec.get("method")
        r["audit"] = flags
        res.append(r)
    doc = {
        "version": nt.NOTA_VERSION,
        "provisional": args.provisional,
        "as_of": args.as_of,
        "pesos": {"rigor": nt.PESO_RIGOR, "juez": nt.PESO_JUEZ, "rigor_componentes": nt.PESOS_RIGOR},
        "formulas": nt.FORMULAS_RIGOR,
        "placebo": nt.placebo_noise(placebo),
        "v2": {
            "version": nt.NOTA_VERSION_V2,
            "pesos": {"rigor": nt.PESO_RIGOR, "juez": nt.PESO_JUEZ, "rigor_componentes": nt.PESOS_RIGOR_V2},
            "formulas": nt.FORMULAS_RIGOR_V2,
            "juez": "10 × mín(1, máx(0, 1 + Δ/2)), Δ = nuestra nota − Numantia (sobre 5)",
            "modulo": nt.module_tesis_v2(
                {r["ticker"]: (None if r.get("nota") is None else r["v2"]["nota"]) for r in res},
                [r["ticker"] for r in res],
            ),
        },
        "tesis": res,
    }
    (out / "notas.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str))
    print("score", len(res), "placebo", doc["placebo"])


def cmd_modules(args) -> None:
    """Nota por módulo (valor intrínseco, DCA, Cerebro, equipo, tesis) con su fórmula."""
    out = Path(args.out)
    x = json.loads(Path(args.inputs).read_text())
    notas = json.loads((out / "notas.json").read_text())
    graded = [r for r in notas["tesis"] if r.get("nota") is not None]
    judged = [r for r in graded if (r.get("juez") or {}).get("delta_vs_ancla") is not None]
    eq = dict(x["equipo"])
    eq["tesis_juzgadas"] = len(judged)
    eq["tesis_en_suelo"] = sum(1 for r in judged if r["juez"]["delta_vs_ancla"] >= -0.05)
    res = {
        "provisional": notas.get("provisional"),
        "valor_intrinseco": nt.grade_valor_intrinseco(x["valor_intrinseco"]),
        "dca": nt.grade_dca(x["dca"]),
        "cerebro": nt.grade_cerebro(x["cerebro"]),
        "equipo": nt.grade_equipo(eq),
        "tesis": {
            "nota": round(sum(r["nota"] for r in graded) / len(graded), 1) if graded else None,
            "formula": "media de las notas por tesis (0,8 × rigor + 0,2 × juez)",
            "n": len(graded),
        },
    }
    if x.get("cerebro_v2"):
        res["cerebro_v2"] = nt.grade_cerebro_v2(x["cerebro_v2"])
    if notas.get("v2"):
        res["tesis_v2"] = notas["v2"]["modulo"]
        eq2 = dict(x["equipo"])
        jud = [r for r in notas["tesis"] if (r.get("juez") or {}).get("delta_vs_ancla") is not None]
        eq2["tesis_juzgadas"] = len(notas["tesis"])  # v2: las que no tienen tesis cuentan como no alcanzadas
        eq2["tesis_en_suelo"] = sum(1 for r in jud if r["juez"]["delta_vs_ancla"] >= -0.05)
        res["equipo_v2"] = nt.grade_equipo(eq2)
    (out / "modulos.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print({k: v.get("nota") for k, v in res.items() if isinstance(v, dict)})


# ------------------------------------------------------------------------------------------------ previsiones


def cmd_forecast_log(args) -> None:
    out = Path(args.out)
    collect = json.loads((out / "collect.json").read_text())
    notas = {}
    if (out / "notas.json").exists():
        notas = {r["ticker"]: r.get("nota") for r in json.loads((out / "notas.json").read_text())["tesis"]}
    lines = []
    for rec in collect:
        if rec.get("price") is None:
            continue
        lines.append(
            nt.forecast_record(
                ticker=rec["ticker"],
                as_of=date.fromisoformat(args.as_of),
                price=float(rec["price"]),
                currency=rec.get("currency"),
                value_per_share=rec.get("value_per_share") or {},
                irr5=rec.get("irr5"),
                method=rec.get("method"),
                analyst=rec.get("consensus"),
                thesis_fingerprint=(rec.get("thesis") or {}).get("fingerprint"),
                commit=args.commit,
                nota=notas.get(rec["ticker"]),
            )
        )
    Path(args.log).write_text(
        "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in lines)
    )
    print("forecast-log", len(lines), args.log)


def cmd_forecast_score(args) -> None:
    import expert_bench as xb

    from app.core.database import SessionLocal

    db = SessionLocal()
    scores = []
    for line in Path(args.log).read_text().splitlines():
        rec = json.loads(line)
        start = date.fromisoformat(rec["as_of"])
        end = date(start.year + args.horizon, start.month, min(start.day, 28))
        if end > date.today():
            continue  # todavía no: nunca se puntúa antes de la fecha
        company = xb._company(db, rec["ticker"])
        price = xb._close_on_or_before(db, company, end) if company else None
        if price is None:
            continue
        divs = xb._dividends_between(db, company, start, end)
        scores.append(
            nt.score_vs_analysts(rec, horizon_years=args.horizon, price_then=price, dividends_per_share=divs)
        )
    print(
        json.dumps(
            {"horizon": args.horizon, "summary": nt.summarize_vs(scores), "scores": scores},
            ensure_ascii=False,
            default=str,
        )[:4000]
    )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--out", required=True)
    c.add_argument("--tickers", default=",".join(TICKERS))
    c.add_argument("--as-of", default=date.today().isoformat())
    c.add_argument("--no-consensus", action="store_true")
    j = sub.add_parser("judge")
    j.add_argument("--out", required=True)
    j.add_argument("--anchors", required=True, help="TICKER=ruta,...,*=ruta (ancla común)")
    j.add_argument("--placebo", default="")
    j.add_argument("--cap-eur", type=float, required=True)
    j.add_argument("--parallel", type=int, default=2)
    s = sub.add_parser("score")
    s.add_argument("--out", required=True)
    s.add_argument("--audit", required=True)
    s.add_argument("--primary", default="", help="benchmarks/fuente_primaria_AAAA-MM-DD.json (baremo v2)")
    s.add_argument("--as-of", default=date.today().isoformat())
    s.add_argument("--provisional", action=argparse.BooleanOptionalAction, default=True)
    fl = sub.add_parser("forecast-log")
    fl.add_argument("--out", required=True)
    fl.add_argument("--log", required=True)
    fl.add_argument("--as-of", default=date.today().isoformat())
    fl.add_argument("--commit", default=None)
    mo = sub.add_parser("modules")
    mo.add_argument("--out", required=True)
    mo.add_argument("--inputs", required=True)
    fs = sub.add_parser("forecast-score")
    fs.add_argument("--log", required=True)
    fs.add_argument("--horizon", type=int, choices=nt.HORIZONTES, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "judge":
        asyncio.run(_judge(args))
    else:
        {
            "collect": cmd_collect,
            "score": cmd_score,
            "modules": cmd_modules,
            "forecast-log": cmd_forecast_log,
            "forecast-score": cmd_forecast_score,
        }[args.cmd](args)


if __name__ == "__main__":
    main()
