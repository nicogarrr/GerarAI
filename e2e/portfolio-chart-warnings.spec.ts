import { expect, test } from "@playwright/test";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { seedMarketPrices } from "./fixtures/market-prices";
import { seedFxRates } from "./fixtures/fx-rates";
import { E2E_UI_BACKEND_URL } from "./fixtures/e2e-env";

// Regresion (bug b del lote log-hygiene, 2026-10-12): el log de un run e2e
// del 11/10 mostraba dos warnings de Recharts
// "The width(-1) and height(-1) of chart should be greater than 0" al
// renderizar /portfolio Resumen a 768px con cartera real.
//
// Causa raiz (verificada en node_modules/recharts@3.3.0,
// es6/component/ResponsiveContainer.js): ResponsiveContainer arranca con el
// estado initialDimension = {width: -1, height: -1} y el primer render (antes
// de que el ResizeObserver mida) dispara el warn dev; el chart no se pinta
// con ese estado (devuelve null). En dev React StrictMode monta dos veces:
// dos warnings por UN solo chart. La repro controlada (cartera sembrada,
// 768px) confirmo que el componente que los emitia es el donut
// (PortfolioAllocationChart): el NAV chart no llega a montarse porque
// getPortfolioScores devuelve `history: undefined`
// (lib/actions/portfolio.actions.ts) y PortfolioTabs muestra el placeholder
// "El historial aparecera cuando existan snapshots reales". El fix de
// initialDimension se aplico a AMBOS charts por si el NAV se activa.
//
// Fix: initialDimension con un tamano inicial positivo (la altura fija del
// wrapper, h-[200px]; el ancho es una estimacion del caso movil, NO una
// medicion real — el ResizeObserver la corrige al montar).
//
// Esta spec renderiza /portfolio Resumen con datos reales sembrados
// (companies + precios + FX EUR/USD + transacciones firmadas), exige el
// donut montado con SVG de tamano real, deja constancia del estado del NAV
// (placeholder o chart montado) y falla si reaparece el warning.

test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1 to run browser tests.");

const apiSecret = process.env.RESEARCH_AUTH_SECRET ?? "cavaai-e2e-research-secret-at-least-32-characters";
const apiUser = "e2e-browser-user";
const apiBase = E2E_UI_BACKEND_URL;

function signedHeaders(method: string, path: string, body: Buffer = Buffer.alloc(0)) {
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const nonce = randomUUID().replaceAll("-", "");
  const bodyHash = createHash("sha256").update(body).digest("hex");
  const signature = createHmac("sha256", apiSecret)
    .update(`${apiUser}:${apiUser}:${timestamp}:${nonce}:${method}:${path}:${bodyHash}`)
    .digest("hex");
  return {
    "X-CavaAI-Tenant": apiUser,
    "X-CavaAI-User": apiUser,
    "X-CavaAI-Timestamp": timestamp,
    "X-CavaAI-Nonce": nonce,
    "X-CavaAI-Method": method,
    "X-CavaAI-Path": path,
    "X-CavaAI-Body-Hash": bodyHash,
    "X-CavaAI-Signature": signature,
    "Content-Type": "application/json",
  };
}

async function seedPortfolioWithCharts(request: import("@playwright/test").APIRequestContext) {
  // Tickers sinteticos exclusivos de esta spec (mismo criterio que
  // methodology-disclosure: el tenant e2e es compartido).
  const seeds = [
    { ticker: "E2ECW1", quantity: 5, price: 900 },
    { ticker: "E2ECW2", quantity: 4, price: 700 },
  ];
  // 2 empresas x 2 fechas FIJAS (ancla 2026-09-09). Regla de convivencia
  // con _common_sessions (market.py:378): la sesion de /movers sale de la
  // mediana de counts de los ultimos 10 dias laborables; sembrar muchas
  // empresas x muchos dias la sube y expulsa a COST de ticker-badges
  // (CI rojo en 943949a9). 2x2 deja la mediana <= 3 y la sesion estable
  // incluso en runs parciales (sharding, --grep, reruns).
  const days: { date: string; close: number }[] = [];
  for (let i = 2; i >= 1; i--) {
    const d = new Date(Date.parse("2026-09-09T00:00:00Z") - (i - 1) * 86400000).toISOString().slice(0, 10);
    days.push({ date: d, close: 100 + i });
  }
  for (const s of seeds) {
    const body = Buffer.from(JSON.stringify({
      ticker: s.ticker, name: `${s.ticker} Inc`, exchange: "NASDAQ", currency: "USD",
    }));
    const res = await request.post(`${apiBase}/api/companies/ensure`, {
      data: body, headers: signedHeaders("POST", "/api/companies/ensure", body),
    });
    expect(res.status(), await res.text()).toBeLessThan(300);
    seedMarketPrices(s.ticker, days);
  }
  // FX en la direccion que consulta portfolio_fx_service.py: base=EUR,
  // quote=USD, rate_date <= as_of. Desde antes de la fecha de compra.
  const fxRows: { date: string; rate: number }[] = [];
  for (let i = 0; i < 300; i++) {
    fxRows.push({ date: new Date(Date.parse("2026-01-01T00:00:00Z") + i * 86400000).toISOString().slice(0, 10), rate: 1.087 });
  }
  seedFxRates(apiUser, "EUR", "USD", fxRows);
  for (const s of seeds) {
    const body = Buffer.from(JSON.stringify({
      ticker: s.ticker, action: "buy", quantity: s.quantity, price: s.price,
      trade_date: "2026-01-15", currency: "USD", fees: 0,
    }));
    const res = await request.post(`${apiBase}/api/portfolio/transactions`, {
      data: body, headers: signedHeaders("POST", "/api/portfolio/transactions", body),
    });
    expect(res.status(), await res.text()).toBeLessThan(300);
  }
}

const RECHARTS_SIZE_PATTERNS = ["width(-1)", "height(-1)"];

for (const vp of [
  { name: "desktop", width: 1440, height: 900 },
  { name: "movil-768", width: 768, height: 900 },
]) {
  test(`/portfolio Resumen sin warnings de tamano de Recharts (${vp.name})`, async ({ page, request }) => {
    await seedPortfolioWithCharts(request);
    const consoleLines: string[] = [];
    page.on("console", (m) => consoleLines.push(m.text()));

    await page.setViewportSize({ width: vp.width, height: vp.height });
    await page.goto("/portfolio", { waitUntil: "networkidle", timeout: 60000 });
    // Espera por estado: el donut (dynamic import propio) monta su SVG.
    await page.waitForSelector(".recharts-responsive-container svg", { timeout: 60000 });
    await page.waitForTimeout(4000);

    // El donut es el componente del warning original: debe estar montado.
    await expect(
      page.locator("#portfolio-allocation-legend"),
      "la distribucion (donut) debe estar montada con la cartera sembrada"
    ).toBeAttached();

    // TODO chart montado (donut hoy; NAV si algun dia history deja de ser
    // undefined) debe tener un SVG con tamano real >0.
    const containers = page.locator(".recharts-responsive-container");
    const charts = await containers.count();
    expect(charts, "al menos el donut debe estar montado").toBeGreaterThanOrEqual(1);
    for (let i = 0; i < charts; i++) {
      const box = await containers.nth(i).locator("svg").first().boundingBox();
      expect(box && box.width > 0 && box.height > 0, `chart #${i} con SVG de tamano real`).toBeTruthy();
    }

    const hits = consoleLines.filter((l) => RECHARTS_SIZE_PATTERNS.some((p) => l.includes(p)));
    expect(
      hits,
      `warnings de Recharts en /portfolio (${vp.name}, ${charts} charts):\n${hits.join("\n").slice(0, 2000)}`
    ).toEqual([]);
  });
}
