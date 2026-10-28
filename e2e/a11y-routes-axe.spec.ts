import { AxeBuilder } from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { seedFxRates } from "./fixtures/fx-rates";
import { seedMarketPrices } from "./fixtures/market-prices";

// Barrido axe-core (via @axe-core/playwright, axe 4.14) de las pantallas
// firmadas principales con datos sembrados, en escritorio y a 375 px.
// Presupuesto: 0 violaciones serias o criticas por pantalla. Ademas falla si
// la consola avisa de un error de hidratacion de React.
//
// No va en el CI bloqueante: corre en .github/workflows/a11y-perf.yml (manual y
// nocturno) con E2E_UI_RUN=1 E2E_A11Y_RUN=1. Cubre lo que a11y-app-axe (sin
// datos, 3 rutas, axe transitivo 4.11) no ve: watchlist con fichas moviles,
// ficha, cartera, impuestos, Cerebro, alertas, ajustes, plan, temas, screener.
//
// Regresiones que fija (barrido del 28-oct-2026):
// - menu de usuario: aria-label sin el texto visible (label-content-name-mismatch);
// - tira de resultados de /inicio: igual, en cada dia;
// - /watchlist movil: <div> suelto dentro del grupo dt/dd de la ficha (definition-list);
// - /screener: enlace «Crea el primero» solo distinguible por color (link-in-text-block);
// - /temas: etiqueta «Caliente» blanco sobre red-500, 3,76:1 (color-contrast).
// - /portfolio y /taxes: h1 -> h3 sin h2 (heading-order, moderada; visto con
//   Lighthouse). En esas dos pantallas el presupuesto incluye esa regla.
test.skip(!process.env.E2E_UI_RUN || !process.env.E2E_A11Y_RUN, "Set E2E_UI_RUN=1 E2E_A11Y_RUN=1 to run the a11y sweep.");
test.describe.configure({ mode: "serial" });

const apiSecret = process.env.RESEARCH_AUTH_SECRET ?? "cavaai-e2e-research-secret-at-least-32-characters";
const apiUser = "e2e-browser-user";
const apiBase = process.env.E2E_UI_BACKEND_URL ?? "http://127.0.0.1:8100";

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

async function post(request: APIRequestContext, path: string, payload: unknown, okStatuses = [200, 201, 409]) {
  const body = Buffer.from(JSON.stringify(payload));
  const res = await request.post(`${apiBase}${path}`, { data: body, headers: signedHeaders("POST", path, body) });
  expect(okStatuses, `${path} -> ${res.status()} ${await res.text()}`).toContain(res.status());
}

// Cartera y watchlist con un valor de EE. UU., uno de Londres en peniques y
// uno de Paris: las fichas, tablas y graficos se pintan con datos, no vacios.
const COMPANIES = [
  { ticker: "AAPL", name: "Apple Inc", exchange: "NASDAQ", currency: "USD", price: 180 },
  { ticker: "MSFT", name: "Microsoft", exchange: "NASDAQ", currency: "USD", price: 400 },
  { ticker: "VOD.L", name: "Vodafone Group", exchange: "LSE", currency: "GBp", price: 72 },
  { ticker: "MC.PA", name: "LVMH", exchange: "EPA", currency: "EUR", price: 650 },
];

let seeded = false;
async function seed(request: APIRequestContext) {
  if (seeded) return;
  for (const c of COMPANIES) {
    await post(request, "/api/companies/ensure", { ticker: c.ticker, name: c.name, exchange: c.exchange, currency: c.currency }, [200, 201]);
    const rows: { date: string; close: number }[] = [];
    for (let i = 0; i < 120; i++) {
      const d = new Date(Date.UTC(2026, 9, 27) - i * 86_400_000);
      if (d.getUTCDay() === 0 || d.getUTCDay() === 6) continue;
      rows.push({ date: d.toISOString().slice(0, 10), close: Number((c.price * (1 - i * 0.001)).toFixed(2)) });
    }
    seedMarketPrices(c.ticker, rows);
    await post(request, "/api/watchlist", { symbol: c.ticker });
  }
  const fx: { date: string; rate: number }[] = [];
  for (let i = 0; i < 700; i++) fx.push({ date: new Date(Date.UTC(2025, 0, 1) + i * 86_400_000).toISOString().slice(0, 10), rate: 1.08 });
  seedFxRates(apiUser, "EUR", "USD", fx);
  seedFxRates(apiUser, "EUR", "GBP", fx.map((r) => ({ ...r, rate: 0.85 })));
  const txs = [
    { ticker: "AAPL", action: "buy", quantity: 10, price: 150, trade_date: "2025-03-10", currency: "USD" },
    { ticker: "AAPL", action: "sell", quantity: 4, price: 190, trade_date: "2025-11-12", currency: "USD" },
    { ticker: "MSFT", action: "buy", quantity: 5, price: 350, trade_date: "2025-02-03", currency: "USD" },
    { ticker: "VOD.L", action: "buy", quantity: 1000, price: 70, trade_date: "2025-04-01", currency: "GBp" },
    { ticker: "MC.PA", action: "buy", quantity: 3, price: 600, trade_date: "2025-05-05", currency: "EUR" },
  ];
  for (const t of txs) await post(request, "/api/portfolio/transactions", { ...t, fees: 1 }, [200, 201]);
  seeded = true;
}

const ROUTES = [
  "/inicio",
  "/watchlist",
  "/research/MSFT",
  "/research/MSFT/tesis",
  "/portfolio",
  "/portfolio/intelligence",
  "/taxes",
  "/research/assistant",
  "/alerts",
  "/settings",
  "/plan",
  "/screener",
  "/temas",
  "/calendar",
];
const VIEWPORTS = [
  { name: "escritorio", width: 1366, height: 768 },
  { name: "movil-375", width: 375, height: 812 },
];
// Reglas de impacto moderado ya arregladas por pantalla: presupuesto 0 también.
const EXTRA_RULES: Record<string, string[]> = {
  "/portfolio": ["heading-order"],
  "/taxes": ["heading-order"],
};
const HYDRATION = /hydrat|did not match|server rendered (html|text)|text content does not match/i;

async function serious(page: Page, extraRules: string[] = []) {
  // El overlay de dev de Next no es parte de la app.
  await page.addStyleTag({ content: "nextjs-portal{display:none!important}" });
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const found = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  if (extraRules.length === 0) return found;
  // heading-order es «best-practice» en axe: se pide por regla, solo aquí.
  const extra = await new AxeBuilder({ page }).withRules(extraRules).analyze();
  return [...found, ...extra.violations];
}

for (const vp of VIEWPORTS) {
  for (const path of ROUTES) {
    test(`a11y ${path} (${vp.name}): 0 violaciones axe serias/criticas y sin avisos de hidratacion`, async ({ page, request }) => {
      await seed(request);
      const hydration: string[] = [];
      page.on("console", (m) => {
        if ((m.type() === "error" || m.type() === "warning") && HYDRATION.test(m.text())) hydration.push(m.text().slice(0, 500));
      });
      page.on("pageerror", (e) => {
        if (HYDRATION.test(String(e))) hydration.push(String(e).slice(0, 500));
      });
      await page.setViewportSize({ width: vp.width, height: vp.height });
      const response = await page.goto(path, { timeout: 120_000 });
      expect(response?.status(), `${path} respondio ${response?.status()}`).toBeLessThan(400);
      await page.waitForLoadState("networkidle").catch(() => undefined);
      await expect(page.locator("main#content")).toBeVisible();
      const violations = await serious(page, EXTRA_RULES[path]);
      const report = violations
        .map((v) => `${v.id} (${v.impact}): ${v.help}\n  ${v.nodes.slice(0, 5).map((n) => `${n.target.join(" ")} ${n.html.slice(0, 160)}`).join("\n  ")}`)
        .join("\n");
      expect(violations, report).toEqual([]);
      expect(hydration, hydration.join("\n")).toEqual([]);
    });
  }
}
