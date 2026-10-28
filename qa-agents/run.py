"""Lanza agentes persona (browser-use + LLM) contra una instancia local de GerarAI.

Uso:
  python qa-agents/run.py --base http://127.0.0.1:3720 --out qa-agents/out [--only slug,slug] [--parallel 6]

LLM: el mismo que usa la app (OpenCode Go, OpenAI-compatible). Variables:
  QA_LLM_BASE_URL (por defecto OPENCODE_GO_BASE_URL o https://opencode.ai/zen/go/v1)
  QA_LLM_MODEL    (por defecto glm-5.3; respaldo QA_LLM_FALLBACK_MODEL, por defecto deepseek-v4-pro)
  QA_LLM_API_KEY  (por defecto OPENCODE_GO_API_KEY)
  QA_LLM_PROVIDER=anthropic usa la API de Anthropic (QA_LLM_MODEL por defecto claude-haiku-4-5).
Chromium: QA_CHROME (por defecto el de Playwright).

OJO, consumo: una pasada completa (7 personas) son ~250 llamadas con prompts de DOM largos.
El 28/10/2026 tres pasadas seguidas agotaron el límite SEMANAL de OpenCode Go (429
GoUsageLimitError), que es el mismo que usa el chat Cerebro en producción. Lanza pocas personas
(--only) y no lo programes en cron sin un plan con margen.
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from monitor import Monitor  # noqa: E402
from personas import PERSONAS, Persona, task_for  # noqa: E402


def _chrome() -> str:
    if os.environ.get("QA_CHROME"):
        return os.environ["QA_CHROME"]
    cands = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")))
    if not cands:
        raise SystemExit("No hay Chromium: ejecuta `playwright install chromium` o define QA_CHROME")
    return cands[-1]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _llm(model_override: str | None = None):
    from browser_use.llm.openai.chat import ChatOpenAI

    if os.environ.get("QA_LLM_PROVIDER") == "anthropic":
        from browser_use.llm.anthropic.chat import ChatAnthropic

        return ChatAnthropic(
            model=model_override or os.environ.get("QA_LLM_MODEL") or "claude-haiku-4-5",
            api_key=os.environ["QA_LLM_API_KEY"],
            base_url=os.environ.get("QA_LLM_BASE_URL") or None,
            max_tokens=4096,
            timeout=120,
            max_retries=3,
        )

    key = os.environ.get("QA_LLM_API_KEY") or os.environ.get("OPENCODE_GO_API_KEY")
    if not key:
        raise SystemExit("Falta QA_LLM_API_KEY / OPENCODE_GO_API_KEY")
    base_url = os.environ.get("QA_LLM_BASE_URL") or os.environ.get("OPENCODE_GO_BASE_URL") or "https://opencode.ai/zen/go/v1"
    # glm-5.3 (misma suscripción OpenCode Go que la app): acepta response_format
    # json_schema de forma estable. deepseek-v4.1-flash, el modelo del chat de
    # la app, lo rechaza a ratos ("response_format type is unavailable now") y
    # sin él responde con su formato nativo <｜DSML｜ calls>; queda de respaldo.
    model = model_override or os.environ.get("QA_LLM_MODEL") or "glm-5.3"
    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=key,
        # OpenCode Go exige una sesión por conversación para enrutar.
        default_headers={"x-opencode-session": str(uuid.uuid4())},
        # json_schema forzado: sin él, DeepSeek responde a veces con su formato
        # nativo de tool-calls (<｜DSML｜ calls>) y browser-use no lo parsea.
        dont_force_structured_output=False,
        add_schema_to_system_prompt=True,
        temperature=0.4,
        timeout=120,
        max_retries=3,
    )


async def run_persona(p: Persona, base: str, out: Path) -> dict:
    from browser_use import Agent, BrowserProfile, BrowserSession
    from playwright.async_api import async_playwright

    pdir = out / p.slug
    if pdir.exists():
        shutil.rmtree(pdir)
    pdir.mkdir(parents=True)
    port = _free_port()
    udd = tempfile.mkdtemp(prefix=f"qa-{p.slug}-")
    w, h = (375, 812) if p.mobile else (1280, 800)
    chrome = subprocess.Popen(
        [_chrome(), "--headless=new", f"--remote-debugging-port={port}", "--no-sandbox", "--disable-gpu",
         "--no-first-run", "--no-default-browser-check", f"--user-data-dir={udd}", f"--window-size={w},{h}",
         "--lang=es-ES", base + p.start_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    t0 = time.time()
    result: dict = {"persona": p.slug, "goal": p.goal}
    pw = None
    monitor = None
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1).read()
                break
            except Exception:  # noqa: BLE001 - aún arrancando
                await asyncio.sleep(0.5)
        pw = await async_playwright().start()
        browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        monitor = Monitor(browser, pdir, p.slug, base)
        monitor.attach()
        if p.mobile:
            for ctx in browser.contexts:
                for page in ctx.pages:
                    cdp = await ctx.new_cdp_session(page)
                    await cdp.send("Emulation.setDeviceMetricsOverride", {"width": 375, "height": 812, "deviceScaleFactor": 2, "mobile": True})
                    await cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True})
        scanner = asyncio.create_task(monitor.run_scanner())
        files = [str(HERE / "fixtures" / f) for f in p.upload_files]
        profile = BrowserProfile(
            viewport={"width": w, "height": h},
            window_size={"width": w, "height": h},
            headless=True,
            highlight_elements=False,
            wait_between_actions=0.6,
        )
        session = BrowserSession(cdp_url=f"http://127.0.0.1:{port}", browser_profile=profile)
        agent = Agent(
            task=task_for(p, base),
            llm=_llm(),
            fallback_llm=None if os.environ.get("QA_LLM_PROVIDER") == "anthropic" else _llm(os.environ.get("QA_LLM_FALLBACK_MODEL", "deepseek-v4-pro")),
            browser_session=session,
            use_vision=False,
            available_file_paths=files or None,
            max_failures=4,
            step_timeout=240,
            llm_timeout=150,
            register_new_step_callback=monitor.on_step,
            save_conversation_path=str(pdir / "conversation"),
            use_judge=False,
            # Chromium ya arranca en start_path; sin esto browser-use abre la
            # primera URL del texto (la raíz pública) y el agente se pierde.
            directly_open_url=False,
            calculate_cost=False,
        )
        budget = float(os.environ.get("QA_PERSONA_TIMEOUT", "900"))
        try:
            history = await asyncio.wait_for(agent.run(max_steps=p.max_steps), timeout=budget)
        except TimeoutError:
            result["timed_out"] = budget
            history = agent.history
        result["final"] = history.final_result()
        result["steps"] = history.number_of_steps()
        result["errors"] = [e for e in history.errors() if e][:10]
        result["urls"] = [u for u in history.urls() if u][:80]
        scanner.cancel()
        try:
            await session.kill()
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001 - el informe recoge el fallo del arnés
        result["harness_error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()[-3000:]
    finally:
        if monitor:
            await monitor.close()
            result["visited"] = monitor.visited
            result["findings"] = len(monitor.findings)
        if pw:
            try:
                await pw.stop()
            except Exception:  # noqa: BLE001
                pass
        chrome.kill()
        shutil.rmtree(udd, ignore_errors=True)
        result["seconds"] = round(time.time() - t0, 1)
        (pdir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("QA_BASE_URL", "http://127.0.0.1:3720"))
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--only", default="")
    ap.add_argument("--parallel", type=int, default=6)
    ap.add_argument("--max-steps", type=int, default=0)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    chosen = [p for p in PERSONAS if not args.only or p.slug in args.only.split(",")]
    if args.max_steps:
        chosen = [Persona(**{**p.__dict__, "max_steps": args.max_steps}) for p in chosen]
    sem = asyncio.Semaphore(args.parallel)

    async def guarded(p: Persona) -> dict:
        async with sem:
            print(f"[qa] ▶ {p.slug}", flush=True)
            r = await run_persona(p, args.base, out)
            print(f"[qa] ■ {p.slug}: {r.get('findings')} hallazgos, {r.get('steps')} pasos, {r.get('seconds')} s"
                  + (f" ERROR {r['harness_error']}" if r.get("harness_error") else ""), flush=True)
            return r

    results = await asyncio.gather(*(guarded(p) for p in chosen))
    (out / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    # El arnés informa; no falla el job por hallazgos (no bloquea CI).
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
