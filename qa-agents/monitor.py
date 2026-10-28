"""Vigilante determinista que acompaña a cada agente persona.

Se conecta por CDP al mismo Chromium que maneja el agente (browser-use) y
registra, con captura de pantalla, todo lo que un usuario real vería roto:
errores de consola y de página, respuestas 4xx/5xx, peticiones caídas,
texto con NaN/undefined/null/Infinity/[object Object], desborde horizontal
y patrones de importes sospechosos. No decide nada: anota hechos.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

BAD_TEXT = [
    ("nan", r"\bNaN\b"),
    ("undefined", r"\bundefined\b"),
    ("null", r"(?<![\w-])null(?![\w-])"),
    ("infinity", r"[-+]?\bInfinity\b|∞\s*%"),
    ("object_object", r"\[object Object\]"),
    ("invalid_date", r"Invalid Date"),
]

# Ruido conocido del modo desarrollo de Next.js, no de la app.
IGNORED_URL = re.compile(r"(/_next/webpack-hmr|/__nextjs|favicon\.ico|/_next/static/.*\.map$)")
IGNORED_CONSOLE = re.compile(
    r"(Download the React DevTools|\[Fast Refresh\]|\[HMR\]|webpack-hmr|Failed to load resource: net::ERR_ABORTED)"
)

SCAN_JS = r"""
(patterns) => {
  const out = {bad: [], overflow: null, path: location.pathname + location.search};
  const body = document.body;
  if (!body) return out;
  const text = body.innerText || '';
  for (const [kind, src] of patterns) {
    const re = new RegExp('.{0,50}' + src + '.{0,50}');
    const m = text.match(re);
    if (m) out.bad.push({kind, snippet: m[0].replace(/\s+/g, ' ').trim()});
  }
  const cw = document.documentElement.clientWidth;
  const sw = document.documentElement.scrollWidth;
  if (sw > cw + 2) {
    const wide = [];
    for (const el of document.querySelectorAll('body *')) {
      const r = el.getBoundingClientRect();
      const st = getComputedStyle(el);
      if (r.width > 0 && r.right > cw + 2 && st.position !== 'fixed' && st.visibility !== 'hidden') {
        let p = el.parentElement, clipped = false;
        while (p && p !== body) {
          const ps = getComputedStyle(p);
          if (/(auto|scroll|hidden|clip)/.test(ps.overflowX)) { clipped = true; break; }
          p = p.parentElement;
        }
        if (!clipped) wide.push(el.tagName.toLowerCase() + '.' + String(el.className || '').slice(0, 60) + ' right=' + Math.round(r.right));
        if (wide.length >= 4) break;
      }
    }
    if (wide.length) out.overflow = {scrollWidth: sw, clientWidth: cw, elements: wide};
  }
  // Importes absurdos: más de 9 cifras enteras con símbolo de moneda suele ser ×100 o unidades mal.
  const money = text.match(/(?:[€$£]\s?\d{1,3}(?:[.,\s]\d{3}){3,}|\d{1,3}(?:[.,\s]\d{3}){3,}(?:[.,]\d+)?\s?(?:€|EUR|USD|GBP|\$|£))/);
  if (money) out.bad.push({kind: 'huge_amount', snippet: money[0]});
  const pct = text.match(/[-+]?\d{4,}(?:[.,]\d+)?\s?%/);
  if (pct) out.bad.push({kind: 'huge_percent', snippet: pct[0]});
  return out;
}
"""


@dataclass
class Finding:
    persona: str
    kind: str
    detail: str
    url: str
    ts: float = field(default_factory=time.time)
    screenshot: str | None = None
    step: int | None = None


class Monitor:
    def __init__(self, browser, outdir: Path, persona: str, base_url: str):
        self.browser = browser
        self.outdir = outdir
        self.persona = persona
        self.base_host = urlparse(base_url).netloc
        self.findings: list[Finding] = []
        self._seen: set[str] = set()
        self.step = 0
        self._pages: set = set()
        self._stop = asyncio.Event()
        self._log = (outdir / "findings.jsonl").open("a", encoding="utf-8")
        (outdir / "shots").mkdir(parents=True, exist_ok=True)
        self.visited: list[str] = []

    # --- enganche -------------------------------------------------------
    def attach(self) -> None:
        for ctx in self.browser.contexts:
            ctx.on("page", self._watch_page)
            for page in ctx.pages:
                self._watch_page(page)

    def _watch_page(self, page) -> None:
        if page in self._pages:
            return
        self._pages.add(page)
        page.on("console", lambda m, p=page: self._on_console(p, m))
        page.on("pageerror", lambda e, p=page: self._add(p, "pageerror", str(e)[:500]))
        page.on("response", lambda r, p=page: self._on_response(p, r))
        page.on("requestfailed", lambda r, p=page: self._on_failed(p, r))
        page.on("framenavigated", lambda f, p=page: self._on_nav(p, f))

    def _on_nav(self, page, frame) -> None:
        if frame == page.main_frame:
            path = urlparse(frame.url).path
            if not self.visited or self.visited[-1] != path:
                self.visited.append(path)

    def _on_console(self, page, msg) -> None:
        if msg.type != "error":
            return
        text = msg.text
        if IGNORED_CONSOLE.search(text):
            return
        self._add(page, "console_error", text[:500])

    def _on_response(self, page, resp) -> None:
        status = resp.status
        url = resp.url
        if status < 400 or IGNORED_URL.search(url):
            return
        if urlparse(url).netloc != self.base_host:
            return
        self._add(page, f"http_{status}", f"{resp.request.method} {url[:300]}")

    def _on_failed(self, page, req) -> None:
        failure = req.failure or ""
        if "ERR_ABORTED" in str(failure) or IGNORED_URL.search(req.url):
            return
        if urlparse(req.url).netloc != self.base_host:
            return
        self._add(page, "request_failed", f"{req.method} {req.url[:300]} {failure}")

    # --- registro -------------------------------------------------------
    def _add(self, page, kind: str, detail: str) -> None:
        try:
            url = page.url
        except Exception:  # noqa: BLE001 - página ya cerrada
            url = "?"
        path = urlparse(url).path
        norm = re.sub(r"\d+", "N", detail)[:160]
        key = f"{kind}|{path}|{norm}"
        if key in self._seen:
            return
        self._seen.add(key)
        f = Finding(self.persona, kind, detail, url, step=self.step)
        self.findings.append(f)
        asyncio.get_event_loop().create_task(self._shoot(page, f))

    async def _shoot(self, page, f: Finding) -> None:
        name = f"{len(self.findings):03d}-{f.kind}.png"
        try:
            await page.screenshot(path=str(self.outdir / "shots" / name), timeout=8000)
            f.screenshot = f"shots/{name}"
        except Exception:  # noqa: BLE001 - la captura es un extra
            pass
        self._log.write(json.dumps(asdict(f), ensure_ascii=False) + "\n")
        self._log.flush()

    async def scan(self) -> None:
        for page in list(self._pages):
            try:
                if page.is_closed() or urlparse(page.url).netloc != self.base_host:
                    continue
                res = await page.evaluate(SCAN_JS, BAD_TEXT)
            except Exception:  # noqa: BLE001 - navegación en curso
                continue
            for b in res.get("bad", []):
                self._add(page, f"text_{b['kind']}", b["snippet"])
            if res.get("overflow"):
                ov = res["overflow"]
                self._add(page, "overflow_x", f"scrollWidth={ov['scrollWidth']} clientWidth={ov['clientWidth']} {ov['elements']}")

    async def run_scanner(self, every: float = 2.0) -> None:
        while not self._stop.is_set():
            await self.scan()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=every)
            except TimeoutError:
                pass

    async def on_step(self, *_args) -> None:
        self.step += 1
        await self.scan()

    async def close(self) -> None:
        await self.scan()
        self._stop.set()
        await asyncio.sleep(0.5)
        self._log.close()
