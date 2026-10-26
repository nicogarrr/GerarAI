#!/usr/bin/env python3
"""Rotador semanal del modelo del CLI opencode para este repo (opencode.json).

Decide el valor de "model" cruzando solo fuentes vivas (coste 0):

1. Catálogo servido por OpenCode Zen ... https://opencode.ai/zen/v1/models
2. Precio real y estado (deprecated) ... https://models.dev/api.json (provider "opencode")
3. Ranking LMArena WebDev ............. dataset lmarena-ai/leaderboard-dataset
   (config "webdev", split "latest", categoria "overall") via datasets-server.
4. Identidad exacta y politica de datos . MODEL_MAP (abajo, se mantiene a mano).

Reglas duras:
- Jamas elige un modelo no verificado gratis: input y output a $0 en models.dev
  y no marcado deprecated. El sufijo "-free" del nombre NO es prueba (hay
  modelos gratis sin el, p.ej. big-pickle).
- Solo rota si el retador esta CONFIRMADO mejor: rating_lower(retador) mayor que
  rating_upper(actual) en WebDev Arena (intervalos sin solape). Ante cualquier
  duda, conserva el actual.
- Si el actual no tiene score comparable (stealth o sin mapear), se conserva.
- REQUIRE_ZERO_RETENTION=True limita el pool a modelos con zero-retention
  publicado por OpenCode (https://opencode.ai/v2/docs/console/models/). Si eso
  deja el pool vacio, cae al mejor gratuito rankeado y lo avisa en el issue.
- Modelos gratis servidos sin entrada en MODEL_MAP se listan en un issue del
  repo para mapearlos a mano (titulo que empieza por ISSUE_MARKER).

Sin dependencias externas: solo stdlib.
"""
from __future__ import annotations

import json
import os
import urllib.request

ZEN_MODELS_URL = "https://opencode.ai/zen/v1/models"
MODELS_DEV_URL = "https://models.dev/api.json"
ARENA_ROWS_URL = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=lmarena-ai%2Fleaderboard-dataset&config=webdev&split=latest"
    "&offset={offset}&length=100"
)
CONFIG_PATH = os.environ.get("OPENCODE_CONFIG_PATH", "opencode.json")
ISSUE_MARKER = "opencode-rotator:"

# True = rotar solo entre modelos con zero-retention publicado (tus prompts y
# codigo no se usan para entrenar). False = rotar por puro ranking WebDev entre
# todos los verificados gratis.
REQUIRE_ZERO_RETENTION = False

# Identidades exactas y politica de datos por modelo servido en Zen.
#   arena: nombres EXACTOS en el dataset WebDev (vacio = sin score comparable).
#   zero_retention: True / False / None (None = OpenCode no publica nada).
MODEL_MAP = {
    "space-bunny-free": {
        "arena": [],
        "zero_retention": True,
        "note": "Stealth, sin identidad Arena. OpenCode publica zero-retention: no entrena con tus datos.",
    },
    "muse-spark-1.3-contributor-free": {
        "arena": ["muse-spark-1.3 (xHigh)", "muse-spark-1.3-max"],
        "zero_retention": False,
        "note": "Contributor: OpenCode indica que el proveedor usa el periodo gratis para mejorar el modelo.",
    },
    "muse-spark-1.2-contributor-free": {
        "arena": ["muse-spark-1.2 (xHigh)"],
        "zero_retention": False,
        "note": "Contributor (misma politica de datos que 1.3).",
    },
    "mimo-v2.6-flash-free": {
        "arena": [],  # OJO: mimo-v2.6-pro es el hermano de pago; NO mapear al flash gratis.
        "zero_retention": False,
        "note": "Sin entrada WebDev propia todavia.",
    },
    "mimo-v2.5-free": {
        "arena": ["mimo-v2.5"],
        "zero_retention": False,
        "note": "Mapeo aproximado a mimo-v2.5.",
    },
    "nemotron-3-ultra-free": {
        "arena": [],
        "zero_retention": None,
        "note": "Sin score WebDev.",
    },
    "nemotron-3.5-lightning-free": {
        "arena": [],
        "zero_retention": None,
        "note": "Aparece en Arena Text, no en WebDev.",
    },
    "ling-3.0-flash-fin-free": {
        "arena": [],
        "zero_retention": None,
        "note": "Especializado en finanzas; sin score WebDev.",
    },
    "jev-1.13-free": {
        "arena": [],
        "zero_retention": None,
        "note": "TypeSafe AI (endpoint propio systemone).",
    },
    "big-pickle": {
        "arena": [],
        "zero_retention": None,
        "note": "Stealth; gratis sin sufijo -free.",
    },
}

UA = {"User-Agent": "gerarai-opencode-model-rotator/1.0"}


def fetch_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_arena_webdev():
    """model_name -> {rating, rank, lower, upper, date} (category=overall, fecha mas reciente)."""
    out = {}
    offset = 0
    total = None
    while total is None or offset < total:
        page = fetch_json(ARENA_ROWS_URL.format(offset=offset))
        total = page.get("num_rows_total", 0)
        for row in page.get("rows", []):
            r = row.get("row", {})
            if r.get("category") != "overall":
                continue
            name = r.get("model_name")
            date = r.get("leaderboard_publish_date", "")
            if not name:
                continue
            cur = out.get(name)
            if cur is None or date > cur["date"]:
                out[name] = {
                    "rating": r.get("rating"),
                    "rank": r.get("rank"),
                    "lower": r.get("rating_lower"),
                    "upper": r.get("rating_upper"),
                    "date": date,
                }
        offset += 100
    return out


def free_models():
    """(verificados gratis, servidos sin verificar)."""
    served = {m["id"] for m in fetch_json(ZEN_MODELS_URL).get("data", [])}
    md = fetch_json(MODELS_DEV_URL).get("opencode", {}).get("models", {})
    verified, unverified = [], []
    for mid in sorted(served):
        info = md.get(mid)
        if info is None:
            unverified.append(mid)
            continue
        cost = info.get("cost") or {}
        if (
            cost.get("input") == 0
            and cost.get("output") == 0
            and info.get("status") != "deprecated"
        ):
            verified.append(mid)
    return verified, unverified


def score_of(mid, arena):
    for name in MODEL_MAP.get(mid, {}).get("arena", []):
        if name in arena:
            return arena[name]
    return None


def decide(current, free, arena):
    """Devuelve (elegido, razon, privacy_fallback)."""
    if REQUIRE_ZERO_RETENTION:
        pool = [m for m in free if MODEL_MAP.get(m, {}).get("zero_retention") is True]
    else:
        pool = list(free)
    privacy_fallback = False
    if not pool:
        pool = list(free)
        privacy_fallback = True

    ranked = [(m, score_of(m, arena)) for m in pool]
    ranked = [(m, s) for m, s in ranked if s]
    best = max(ranked, key=lambda ms: ms[1]["rating"], default=None)

    if current in pool:
        cur = score_of(current, arena)
        if cur and best and best[0] != current and best[1]["lower"] is not None and cur["upper"] is not None:
            if best[1]["lower"] > cur["upper"]:
                return best[0], (
                    f"{best[0]} confirmado mejor en WebDev Arena "
                    f"({best[1]['rating']:.0f} #{best[1]['rank']} vs actual {cur['rating']:.0f} #{cur['rank']}, IC sin solape)"
                ), privacy_fallback
        return current, "sin cambios: no hay retador gratuito confirmado mejor (o el actual no tiene score comparable)", privacy_fallback

    if best:
        return best[0], (
            f"el modelo actual ({current or 'ninguno'}) ya no es elegible; "
            f"se fija el mejor gratuito rankeado: {best[0]} (WebDev #{best[1]['rank']}, {best[1]['rating']:.0f})"
        ), privacy_fallback
    if pool:
        fallback = "space-bunny-free" if "space-bunny-free" in pool else sorted(pool)[0]
        return fallback, f"el actual no es elegible y no hay scores Arena: fallback determinista a {fallback}", privacy_fallback
    return current, "no hay ningun modelo gratuito verificado: se conserva el actual", privacy_fallback


def github_api(method, path, token, body=None):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            **UA,
        },
        data=json.dumps(body).encode() if body is not None else None,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw else {}


def sync_issue(unmapped, privacy_fallback):
    token = os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return
    try:
        issues = github_api("GET", f"/repos/{repo}/issues?state=open&per_page=100", token)
        existing = next(
            (i for i in issues if "pull_request" not in i and i.get("title", "").startswith(ISSUE_MARKER)),
            None,
        )
        if not unmapped and not privacy_fallback:
            if existing:
                github_api("PATCH", f"/repos/{repo}/issues/{existing['number']}", token, {"state": "closed"})
            return
        lines = []
        if unmapped:
            lines.append("Modelos gratuitos servidos por Zen sin entrada en `MODEL_MAP` (no pueden ganar hasta mapearlos a mano):\n")
            lines += [f"- `{m}`" for m in unmapped]
            lines.append(
                "\nPara cada uno: nombre EXACTO en el dataset WebDev de LMArena (o `arena: []`) "
                "y politica de datos segun https://opencode.ai/v2/docs/console/models/."
            )
        if privacy_fallback:
            if REQUIRE_ZERO_RETENTION:
                lines.append(
                    "\n**Aviso de privacidad**: no queda ningun modelo gratuito con zero-retention publicado; "
                    "se ha caido al mejor gratuito rankeado aunque pueda usar datos para entrenar. "
                    "Revisa `REQUIRE_ZERO_RETENTION` en `scripts/opencode_model_rotator.py`."
                )
            else:
                lines.append(
                    "\n**Aviso**: no hay ningun modelo gratuito verificado ahora mismo; se conserva el modelo actual."
                )
        body = "\n".join(lines)
        if existing:
            github_api("PATCH", f"/repos/{repo}/issues/{existing['number']}", token, {"body": body})
        else:
            github_api("POST", f"/repos/{repo}/issues", token, {"title": f"{ISSUE_MARKER} modelos gratuitos sin mapear", "body": body})
    except Exception as exc:  # el issue es secundario: nunca rompe el workflow
        print(f"aviso: no se pudo sincronizar el issue: {exc}")


def main():
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        try:
            cfg = json.load(fh)
        except json.JSONDecodeError:
            print(f"{CONFIG_PATH} no es JSON parseable; no se toca nada.")
            return 0
    current_full = cfg.get("model", "") or ""
    current = current_full.split("/", 1)[-1] if "/" in current_full else current_full

    try:
        arena = fetch_arena_webdev()
        free, unverified = free_models()
    except Exception as exc:
        print(f"aviso: fuente no disponible ({exc}); se conserva {current_full!r}.")
        return 0

    chosen, reason, privacy_fallback = decide(current, free, arena)
    changed = chosen != current and chosen in free
    if changed:
        cfg["model"] = f"opencode/{chosen}"
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
            fh.write("\n")

    unmapped = [m for m in free if m not in MODEL_MAP]
    sync_issue(unmapped, privacy_fallback)

    # Salida para el workflow
    print(f"actual: {current_full or '(sin fijar)'}")
    print(f"elegido: {chosen} | changed: {changed}")
    print(f"razon: {reason}")
    print(f"gratis verificados: {', '.join(free)}")
    if unverified:
        print(f"servidos sin verificar precio: {', '.join(unverified)}")
    if unmapped:
        print(f"sin mapear en MODEL_MAP: {', '.join(unmapped)}")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        rows = ["| modelo | WebDev | zero-retention | nota |", "|---|---|---|---|"]
        for m in free:
            s = score_of(m, arena)
            score = f"#{s['rank']} ({s['rating']:.0f})" if s else "-"
            zr = MODEL_MAP.get(m, {}).get("zero_retention")
            rows.append(f"| `{m}` | {score} | {zr} | {MODEL_MAP.get(m, {}).get('note', 'sin mapear')} |")
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## OpenCode model rotator\n\n")
            fh.write(f"- actual: `{current_full or '(sin fijar)'}`\n- elegido: `{chosen}` (changed={changed})\n- {reason}\n\n")
            fh.write("\n".join(rows) + "\n")

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")
            fh.write(f"model={chosen}\n")
            fh.write("reason<<ROTATOR_EOF\n")
            fh.write(reason.replace("\n", " ") + "\nROTATOR_EOF\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
