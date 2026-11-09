"""Benchmark del equipo de expertos de la tesis: rigor, estabilidad, ablación, juez ciego, coste y previsiones.

Uso (desde data-engine, con la base y el proveedor de la app configurados):

    python scripts/expert_bench.py rigor --out DIR                      # sin modelo: tesis guardadas
    python scripts/expert_bench.py live --out DIR --tickers POOL,CB --runs 3 --cap-eur 1.5
    python scripts/expert_bench.py judge --out DIR --cap-eur 0.6        # juez ciego, dos órdenes
    python scripts/expert_bench.py forecast-log --out FILE.jsonl        # registro de previsiones con fecha
    python scripts/expert_bench.py forecast-score --log FILE.jsonl --horizon 1

Reglas: solo el proveedor y la configuración de la app (``create_llm_provider``); temperatura 0; sin
reintentos propios; un 429 para la corrida entera y se anota. NO hay backtest de la prosa contra
rentabilidades pasadas: el modelo sabe lo que pasó después (look-ahead). La prueba de valor predictivo
es el registro de previsiones puntuado a 1 y 3 años.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import expert_bench as eb  # noqa: E402


class Stop(Exception):
    """429 del proveedor o tope de gasto: se para todo y se anota."""


class Meter:
    """Envuelve el proveedor de la app: cuenta llamadas, tokens, segundos y € por rol, y aplica el tope."""

    def __init__(self, provider: Any, cap_eur: float, log_path: Path):
        self.provider, self.cap, self.log_path = provider, cap_eur, log_path
        self.spent = 0.0
        self.stopped: str | None = None
        self.calls: list[dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.provider, name)

    async def complete(self, request: Any) -> Any:
        from app.services.budget import BudgetController

        role = (getattr(request, "metadata", None) or {}).get("expert_team_task") or getattr(
            request, "task", "?"
        )
        if self.stopped:
            raise Stop(self.stopped)
        if self.spent >= self.cap:
            self.stopped = f"tope de gasto {self.cap:.2f} € alcanzado"
            raise Stop(self.stopped)
        t0 = time.time()
        try:
            resp = await self.provider.complete(request)
        except Exception as exc:
            text = f"{type(exc).__name__}: {exc}"
            if "429" in text or "rate" in text.lower():
                self.stopped = "429 del proveedor: " + text[:200]
            self._log({"role": role, "seconds": time.time() - t0, "ok": False, "error": text[:300]})
            raise
        usage = getattr(resp, "usage", None)
        it, ot = int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)
        cost = BudgetController.estimate_cost_eur(getattr(resp, "model", None) or "unknown", it, ot)
        self.spent += cost
        self._log(
            {
                "role": role,
                "seconds": round(time.time() - t0, 1),
                "input_tokens": it,
                "output_tokens": ot,
                "cost_eur": cost,
                "ok": True,
                "model": getattr(resp, "model", None),
            }
        )
        return resp

    def _log(self, row: dict[str, Any]) -> None:
        self.calls.append(row)
        with self.log_path.open("a") as fh:
            fh.write(json.dumps(row, default=str) + "\n")


def _session():
    from app.core.database import SessionLocal

    db = SessionLocal()
    db.info["tenant_id"] = 1
    db.info["user_id"] = "expert-bench"
    return db


def _company(db, ticker: str):
    from sqlalchemy import select

    from app.models.entities import Company

    return db.scalars(select(Company).where(Company.ticker == ticker)).first()


def _commit() -> str | None:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10
            ).stdout.strip()
            or None
        )
    except Exception:  # noqa: BLE001
        return None


def rendered_text(sections: dict[str, str], markers: dict[str, str], ctx: Any) -> str:
    from app.services.expert_team.thesis_v2 import active_sections, render

    rend = render(sections, markers)
    return "\n\n".join(f"## {title}\n{rend.get(k, '')}" for k, title, _p, _t in active_sections(ctx))


def company_evidence(db, company: Any, limit: int = 5000) -> list[str]:
    """Todo el texto ingerido de la empresa (documentos y guía citada): contra esto se comprueba una cita."""
    from sqlalchemy import select

    from app.models.entities import Document, DocumentChunk

    rows = db.scalars(
        select(DocumentChunk.text)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.company_id == company.id)
        .limit(limit)
    ).all()
    return [" ".join((t or "").split()) for t in rows if t]


def rigor_for(
    db, ticker: str, doc: dict[str, Any], *, today: date, stored_markers: dict[str, str] | None = None
) -> dict[str, Any]:
    """Métricas de rigor de una tesis v2 (secciones con marcadores tal como las dejó el modelo)."""
    from app.services.expert_team.thesis_v2 import (
        active_sections,
        build_context,
        thesis_markers,
        unknown_markers,
    )

    company = _company(db, ticker)
    ctx = build_context(db, company, today=today, tenant_id=1)
    sections = doc.get("sections") or {}
    markers = thesis_markers(ctx) if ctx.valuation.get("status") in ("ok", "not_meaningful") else {}
    keys = [k for k, *_ in active_sections(ctx)] if markers else list(sections)
    text = rendered_text(sections, markers, ctx) if markers else "\n".join(sections.values())
    evidence = (
        [p.get("text") or "" for p in ctx.passages]
        + company_evidence(db, company)
        + eb.evidence_strings([ctx.valuation, ctx.switches, ctx.guidance, list(markers.values())])
    )
    stored_markers = stored_markers if stored_markers is not None else markers
    return {
        "ticker": ticker,
        "status": doc.get("status"),
        "llm_calls": doc.get("llm_calls"),
        "probability_choice": doc.get("probability_choice"),
        "free_numbers_final": sum(len(v) for v in eb.free_numbers_by_section(sections).values()),
        "unknown_markers_final": sum(len(unknown_markers(v, stored_markers)) for v in sections.values()),
        "guard_problems": eb.classify_problems(doc.get("problems") or []),
        "quotes": eb.check_quotes(eb.extract_quotes(text), evidence),
        "quotes_attributed": eb.check_quotes(eb.extract_attributed_quotes(text), evidence),
        "sections": eb.sections_filled(sections, keys),
        "kill_switches": eb.kill_switch_report(ctx.switches),
        "method": eb.method_fit(
            eb.REFERENCE_TYPES.get(ticker),
            (ctx.valuation.get("method") or {}).get("chosen"),
            text,
            (ctx.valuation.get("method") or {}).get("kind"),
        ),
        "source": eb.source_check(ctx.valuation) if markers else None,
        "valuation_status": ctx.valuation.get("status"),
    }


def cmd_rigor(args) -> None:
    from sqlalchemy import select

    from app.models.declared_input_value import DeclaredInputValue
    from app.models.entities import Company

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    db = _session()
    rows = db.execute(
        select(Company.ticker, DeclaredInputValue)
        .join(Company, Company.id == DeclaredInputValue.company_id)
        .where(DeclaredInputValue.input_key == "thesis_v2", DeclaredInputValue.superseded_at.is_(None))
    ).all()
    res = []
    for ticker, row in sorted(rows, key=lambda r: r[0]):
        doc = (row.metadata_ or {}).get("thesis") or {}
        try:
            res.append(
                rigor_for(
                    db,
                    ticker,
                    doc,
                    today=row.as_of or date.today(),
                    stored_markers=dict((row.metadata_ or {}).get("markers") or {}),
                )
            )
        except Exception as exc:  # noqa: BLE001
            res.append({"ticker": ticker, "error": f"{type(exc).__name__}: {exc}"[:300]})
        db.rollback()
    (out / "rigor.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print("rigor", len(res))


# ------------------------------------------------------------------------------------------- corridas con modelo

VARIANTS = ("completa", "sin_pasajes", "sin_guia", "sin_analistas", "sin_insiders")


def _ablate(ctx: Any, variant: str) -> Any:
    """Quita la aportación de un rol a la entrada del redactor; el resto queda idéntico (misma regla de
    secciones opcionales que ``build_context``)."""
    import copy

    c = copy.copy(ctx)
    if variant == "sin_pasajes":  # quien reúne evidencia de los documentos
        c.passages = []
    elif variant == "sin_guia":  # el contraste con la guía de la empresa
        c.guidance = []
        c.switches = [s for s in ctx.switches if not str(s.get("key", "")).startswith("guia.")]
    elif variant == "sin_analistas":  # estimaciones y precios objetivo de analistas citados en prensa
        c.analysts, c.price_targets = [], []
    elif variant == "sin_insiders":  # compras y ventas de insiders (Form 4)
        c.insiders = None
    if variant in ("sin_guia", "sin_analistas"):
        c.optional = {k: v for k, v in ctx.optional.items() if k != "consenso_guia"}
        if getattr(c, "guidance", None):
            c.optional["consenso_guia"] = "la empresa da previsiones citadas en sus notas de resultados"
        elif getattr(c, "analysts", None) or getattr(c, "price_targets", None):
            c.optional["consenso_guia"] = "hay estimaciones de analistas citadas de la prensa"
    return c


async def _thesis_run(meter: Meter, db, ticker: str, ctx: Any, variant: str, run: int, out: Path) -> None:
    from app.services.expert_team.service import provider_reasoner
    from app.services.expert_team.thesis_v2 import thesis_markers, write_thesis

    path = out / f"v2_{ticker}_{variant}_{run}.json"
    if path.exists():
        return
    reasoner = provider_reasoner(meter, db=None, temperature=0.0)
    c = _ablate(ctx, variant)
    t0 = time.time()
    try:
        res = await write_thesis(reasoner=reasoner, ctx=c, cached=None)
    except Stop as exc:
        print("STOP", ticker, variant, run, exc, flush=True)
        return
    doc = {
        "ticker": ticker,
        "variant": variant,
        "run": run,
        "status": res.status,
        "sections": res.sections,
        "problems": res.problems,
        "llm_calls": res.llm_calls,
        "probability_choice": res.probability_choice,
        "probability_reason": res.probability_reason,
        "seconds": round(time.time() - t0, 1),
        "markers": thesis_markers(c),
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, default=str))
    print("v2", ticker, variant, run, res.status, res.llm_calls, f"{meter.spent:.3f}€", flush=True)


async def _sotp_run(meter: Meter, ticker: str, run: int, out: Path) -> None:
    from app.services.expert_team.models import RunContext
    from app.services.expert_team.service import provider_reasoner
    from app.services.expert_team.sotp_valuer import run_sotp_valuer

    path = out / f"sotp_{ticker}_{run}.json"
    if path.exists():
        return
    db = _session()
    captured: list[dict[str, Any]] = []
    base = provider_reasoner(meter, db=None, temperature=0.0)

    async def reasoner(system: str, user: str, max_tokens: int, task: str) -> str:
        text = await base(system, user, max_tokens, task)
        captured.append({"task": task, "user": user, "response": text})
        return text

    t0 = time.time()
    try:
        res = await run_sotp_valuer(
            db,
            ctx=RunContext(tenant_id=1, ticker=ticker, mode="thesis", lang="es"),
            reasoner=reasoner,
            cached=None,
        )
    except Stop as exc:
        print("STOP sotp", ticker, run, exc, flush=True)
        return
    except Exception as exc:  # noqa: BLE001 - p. ej. Postgres corta la sesión «idle in transaction»
        # mientras el valorador espera al modelo: se anota como resultado, sin reintento.
        path.write_text(
            json.dumps(
                {
                    "ticker": ticker,
                    "run": run,
                    "status": f"error:{type(exc).__name__}",
                    "error": str(exc)[:300],
                    "seconds": round(time.time() - t0, 1),
                }
            )
        )
        print("sotp error", ticker, run, type(exc).__name__, flush=True)
        return
    finally:
        try:
            db.rollback()
            db.close()
        except Exception:  # noqa: BLE001
            pass
    quotes: dict[str, Any] = {"quotes": 0, "not_literal": 0, "examples": []}
    for cap in captured:
        try:
            payload = json.loads(cap["user"])
        except ValueError:
            payload = cap["user"]
        from app.llm.json import parse_json_response

        try:
            parsed = parse_json_response(cap["response"])
        except Exception:  # noqa: BLE001
            parsed = None
        q = eb.check_quotes(eb.quotes_in_json(parsed), eb.evidence_strings(payload))
        quotes["quotes"] += q["quotes"]
        quotes["not_literal"] += q["not_literal"]
        quotes["examples"] += q["examples"]
    d: dict[str, Any] = dict(vars(res))
    doc = {
        "ticker": ticker,
        "run": run,
        "status": d.get("status"),
        "value_per_share": d.get("value_per_share"),
        "classification": d.get("classification"),
        "problems": d.get("problems"),
        "llm_calls": d.get("llm_calls"),
        "quotes": quotes,
        "seconds": round(time.time() - t0, 1),
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, default=str))
    print("sotp", ticker, run, doc["status"], doc["value_per_share"], f"{meter.spent:.3f}€", flush=True)


def _provider(cap: float, out: Path) -> Meter:
    from app.llm.factory import create_llm_provider

    return Meter(create_llm_provider(), cap, out / "calls.jsonl")


async def _live(args) -> None:
    from app.services.expert_team.thesis_v2 import build_context, thesis_fingerprint

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    meter = _provider(args.cap_eur, out)
    tickers = [t for t in args.tickers.split(",") if t]
    db = _session()
    ctxs, fps = {}, {}
    for t in tickers:
        ctx = build_context(db, _company(db, t), today=date.today(), tenant_id=1)
        if ctx.valuation.get("status") in ("ok", "not_meaningful"):
            ctxs[t] = ctx
            fps[t] = {v: thesis_fingerprint(_ablate(ctx, v)) for v in VARIANTS}
    db.rollback()  # ninguna transacción abierta mientras se espera al modelo
    (out / "fingerprints.json").write_text(json.dumps(fps, indent=1))
    sem = asyncio.Semaphore(args.parallel)
    jobs = []
    for t, ctx in ctxs.items():
        for r in range(1, args.runs + 1):
            jobs.append(("v2", t, ctx, "completa", r))
        for v in VARIANTS[1:]:
            if fps[t][v] == fps[t]["completa"]:
                # Misma entrada que la completa (el rol no aporta nada aquí): no se llama al modelo.
                (out / f"v2_{t}_{v}_1.json").write_text(
                    json.dumps({"ticker": t, "variant": v, "run": 1, "identical_input": True})
                )
                continue
            jobs.append(("v2", t, ctx, v, 1))
    if args.sotp:
        for t in tickers:
            for r in range(1, args.runs + 1):
                jobs.append(("sotp", t, None, "", r))

    async def one(job):
        async with sem:
            if meter.stopped:
                return
            kind, t, ctx, v, r = job
            if kind == "v2":
                await _thesis_run(meter, db, t, ctx, v, r, out)
            else:
                await _sotp_run(meter, t, r, out)

    await asyncio.gather(*(one(j) for j in jobs))
    (out / "live_summary.json").write_text(
        json.dumps(
            {
                "spent_eur": meter.spent,
                "stopped": meter.stopped,
                "calls": len(meter.calls),
                "commit": _commit(),
            },
            indent=1,
        )
    )
    print("LIVE DONE", f"{meter.spent:.3f}€", meter.stopped, flush=True)


# ------------------------------------------------------------------------------------------- juez


async def _judge_pair(meter: Meter, ticker: str, x: str, y: str, tag: str, out: Path) -> None:
    from app.services.expert_team.service import provider_reasoner

    path = out / f"judge_{tag}.json"
    if path.exists():
        return
    reasoner = provider_reasoner(meter, db=None, temperature=0.0)
    verdicts = []
    for a, b in ((x, y), (y, x)):
        try:
            # Margen para el razonamiento del modelo: con 1.500 tokens la respuesta llega vacía.
            text = await reasoner(
                eb.JUDGE_RUBRIC, eb.judge_user_message(ticker, a, b), 8000, "expert_bench.juez"
            )
        except Stop as exc:
            print("STOP judge", tag, exc, flush=True)
            return
        except Exception as exc:  # noqa: BLE001 - sin reintento: el par queda sin veredicto
            print("judge error", tag, type(exc).__name__, flush=True)
            text = ""
        verdicts.append(eb.parse_judge(text))
    doc = {
        "tag": tag,
        "ticker": ticker,
        "first": verdicts[0],
        "swapped": verdicts[1],
        "combined": eb.combine_orders(verdicts[0], verdicts[1]),
    }
    path.write_text(json.dumps(doc, ensure_ascii=False))
    print("judge", tag, doc["combined"], f"{meter.spent:.3f}€", flush=True)


def _v2_text(doc: dict[str, Any]) -> str:
    from app.services.expert_team.thesis_v2 import render

    rend = render(doc.get("sections") or {}, doc.get("markers") or {})
    return "\n\n".join(rend.values())


async def _judge(args) -> None:
    out = Path(args.out)
    meter = _provider(args.cap_eur, out)
    sem = asyncio.Semaphore(args.parallel)
    jobs = []
    for f in [] if args.only_pairs else sorted(out.glob("v2_*_completa_1.json")):
        base = json.loads(f.read_text())
        t = base["ticker"]
        for v in VARIANTS[1:]:
            g = out / f"v2_{t}_{v}_1.json"
            if g.exists():
                other = json.loads(g.read_text())
                if other.get("identical_input"):
                    continue  # misma entrada: misma tesis, diferencia 0 sin juez
                jobs.append((t, _v2_text(base), _v2_text(other), f"{t}_completa_vs_{v}"))
    for pair in json.loads(Path(args.pairs).read_text()) if args.pairs else []:
        # Pares libres: {"ticker", "x": ruta de texto, "y": ruta de texto, "tag"} (p. ej. tesis guardada frente
        # a un informe de referencia).
        jobs.append(
            (
                pair["ticker"],
                Path(pair["x"]).read_text()[:90000],
                Path(pair["y"]).read_text()[:90000],
                pair["tag"],
            )
        )
    for ref in (args.refs or "").split(","):
        if not ref:
            continue
        t, path = ref.split("=", 1)
        f = out / f"v2_{t}_completa_1.json"
        if f.exists() and Path(path).exists():
            jobs.append(
                (
                    t,
                    _v2_text(json.loads(f.read_text())),
                    Path(path).read_text()[:90000],
                    f"{t}_completa_vs_numantia",
                )
            )

    async def one(job: tuple[str, str, str, str]) -> None:
        ticker, text_x, text_y, tag = job
        async with sem:
            if not meter.stopped:
                await _judge_pair(meter, ticker, text_x, text_y, tag, out)

    await asyncio.gather(*(one(j) for j in jobs))
    print("JUDGE DONE", f"{meter.spent:.3f}€", meter.stopped, flush=True)


# ------------------------------------------------------------------------------------------- previsiones


def _latest_sotp_values(db, company) -> dict[str, float]:
    """Valor por acción de cada escenario del SOTP guardado (para las que no tienen TIR)."""
    from sqlalchemy import desc, select

    from app.models.declared_input_value import DeclaredInputValue

    row = db.scalars(
        select(DeclaredInputValue)
        .where(
            DeclaredInputValue.company_id == company.id,
            DeclaredInputValue.input_key == "sotp_user_model",
            DeclaredInputValue.superseded_at.is_(None),
        )
        .order_by(desc(DeclaredInputValue.id))
    ).first()
    model = ((row.metadata_ or {}).get("model") or {}) if row is not None else {}
    out = {}
    for s in model.get("scenarios") or []:
        v = s.get("stated_value_per_share")
        if isinstance(v, int | float):
            out[str(s.get("key"))] = float(v)
    return out


def cmd_forecast_log(args) -> None:
    from sqlalchemy import select

    from app.models.declared_input_value import DeclaredInputValue
    from app.models.entities import Company
    from app.services.expert_team.thesis_v2 import build_context, render, thesis_markers
    from app.services.user_sotp_service import _price

    db = _session()
    tickers = [t for t in (args.tickers or "").split(",") if t]
    rows = dict(
        db.execute(
            select(Company.ticker, DeclaredInputValue)
            .join(Company, Company.id == DeclaredInputValue.company_id)
            .where(DeclaredInputValue.input_key == "thesis_v2", DeclaredInputValue.superseded_at.is_(None))
        ).all()
    )
    today = date.fromisoformat(args.as_of) if args.as_of else date.today()
    commit = _commit()
    lines = []
    for ticker in tickers or sorted(rows):
        company = _company(db, ticker)
        if company is None:
            continue
        row = rows.get(ticker)
        meta = (row.metadata_ or {}) if row is not None else {}
        doc = meta.get("thesis") or {}
        ctx = build_context(db, company, today=today, tenant_id=1)
        val = ctx.valuation
        sp = val.get("starting_point") or {}
        # Precio y divisa del LISTADO (la misma cotización con la que puntúa forecast-score), no los de
        # la valuación: esa ya va pasada a la divisa de los informes (FFH.TO cotiza en CAD y presenta en
        # USD). Sin precio de listado no hay registro.
        price, ccy, _ = _price(db, company)
        if price is None or not ccy:
            db.rollback()
            continue
        claims: list[str] = []
        if doc:
            same = meta.get("valuation_fingerprint") == val.get("fingerprint")
            markers = (
                thesis_markers(ctx)
                if same and val.get("status") in ("ok", "not_meaningful")
                else dict(meta.get("markers") or {})
            )
            concl = render({"c": (doc.get("sections") or {}).get("conclusion", "")}, markers)["c"]
            claims = [s.strip() for s in concl.replace("\n", " ").split(". ") if len(s.strip()) > 40][:3]
        rec = eb.forecast_record(
            ticker=ticker,
            as_of=today,
            price=float(price),
            currency=str(ccy),
            scenarios=val.get("scenarios") or {},
            weighted=val.get("weighted"),
            method=(val.get("method") or {}).get("chosen"),
            probability_choice=doc.get("probability_choice"),
            kill_switches=ctx.switches,
            claims=claims,
            thesis_fingerprint=doc.get("fingerprint"),
            commit=commit,
            valuation_price=sp.get("price"),
            valuation_currency=sp.get("currency"),
        )
        rec["valuation_status"] = val.get("status")
        rec["has_thesis_v2"] = bool(doc)
        rec["sotp_value_per_share"] = _latest_sotp_values(db, company) or None
        lines.append(rec)
        db.rollback()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "a") as fh:
        for rec in lines:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    print("forecast-log", len(lines), args.out)


def _close_on_or_before(db, company, day: date) -> tuple[float, str] | None:
    """Cierre del listado en la semana hasta ``day``, en su divisa principal (la del listado, no la de
    los informes ni un USD por defecto): GBX → GBP, FFH.TO → CAD."""
    from datetime import timedelta

    from app.services.valuation_service import resolve_model_price

    listed = resolve_model_price(db, company.id, as_of=day)
    if listed is None or listed.as_of is None or listed.as_of < day - timedelta(days=7) or not listed.currency:
        return None
    return float(listed.value), listed.currency.upper()


def _dividends_between(db, company, start: date, end: date) -> float:
    from sqlalchemy import func, select

    from app.models.entities import DividendRecord

    total = db.scalar(
        select(func.coalesce(func.sum(DividendRecord.amount), 0)).where(
            DividendRecord.company_id == company.id,
            DividendRecord.ex_date > start,
            DividendRecord.ex_date <= end,
        )
    )
    return float(total or 0.0)


def cmd_forecast_score(args) -> None:
    """Puntúa el registro con el cierre guardado en la app a la fecha de cada horizonte (sin modelo)."""
    db = _session()
    scores, pending = [], 0
    for line in Path(args.log).read_text().splitlines():
        rec = json.loads(line)
        due = date.fromisoformat(rec["score_at"][f"{args.horizon}y"])
        if due > date.today():
            pending += 1
            continue
        company = _company(db, rec["ticker"])
        close = _close_on_or_before(db, company, due) if company is not None else None
        if close is None:
            continue
        price, ccy = close
        rec_ccy = str(rec.get("currency") or "").upper()
        if rec_ccy and ccy != rec_ccy:
            # Registros antiguos llevan el precio pasado a la divisa de los informes: el cierre se pasa a
            # esa divisa con el tipo guardado de esa fecha; sin tipo, score_forecast lo deja N/D.
            from app.services.user_sotp_service import convert_amount

            conv = convert_amount(db, price, ccy, rec_ccy, due)
            if conv is not None:
                price, ccy = conv[0], rec_ccy
        divs = _dividends_between(db, company, date.fromisoformat(rec["as_of"]), due)
        scores.append(
            eb.score_forecast(
                rec, horizon_years=args.horizon, price_then=price, dividends_per_share=divs, price_then_currency=ccy
            )
        )
    print(
        json.dumps(
            {
                "horizon": args.horizon,
                "pending": pending,
                "scores": scores,
                "summary": eb.summarize_scores(scores),
            },
            ensure_ascii=False,
            indent=1,
            default=str,
        )
    )


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rigor")
    r.add_argument("--out", required=True)
    lv = sub.add_parser("live")
    lv.add_argument("--out", required=True)
    lv.add_argument("--tickers", required=True)
    lv.add_argument("--runs", type=int, default=3)
    lv.add_argument("--parallel", type=int, default=4)
    lv.add_argument("--cap-eur", type=float, default=1.0)
    lv.add_argument("--sotp", action="store_true")
    j = sub.add_parser("judge")
    j.add_argument("--out", required=True)
    j.add_argument("--refs", default="")
    j.add_argument("--pairs", default="")
    j.add_argument("--only-pairs", action="store_true")
    j.add_argument("--parallel", type=int, default=4)
    j.add_argument("--cap-eur", type=float, default=0.6)
    fl = sub.add_parser("forecast-log")
    fl.add_argument("--out", required=True)
    fl.add_argument("--as-of", default=None)
    fl.add_argument("--tickers", default="")
    fs = sub.add_parser("forecast-score")
    fs.add_argument("--log", required=True)
    fs.add_argument("--horizon", type=int, choices=eb.HORIZONS, default=1)
    args = p.parse_args(argv)
    os.environ.setdefault("LLM_RESPONSE_CACHE_ENABLED", "true")
    if args.cmd == "rigor":
        cmd_rigor(args)
    elif args.cmd == "live":
        asyncio.run(_live(args))
    elif args.cmd == "judge":
        asyncio.run(_judge(args))
    elif args.cmd == "forecast-log":
        cmd_forecast_log(args)
    else:
        cmd_forecast_score(args)


if __name__ == "__main__":
    main()
