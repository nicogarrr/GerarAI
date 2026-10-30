import { expect, test } from "@playwright/test";
import { seedMarketPrices } from "./fixtures/market-prices";
import { createHash, createHmac, randomUUID } from "node:crypto";

// Quick win UX 5: badges «En cartera / En watchlist» en eventos de noticias.
// Semilla firmada (patrón f339, tenant del bypass de navegador): una
// posición COST, NFLX en watchlist y un evento de cada uno.
test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1 to run browser tests.");

const apiSecret = process.env.RESEARCH_AUTH_SECRET ?? "cavaai-e2e-research-secret-at-least-32-characters";
const apiUser = "e2e-browser-user";
const apiBase = "http://127.0.0.1:8100";

function signedHeaders(method: string, path: string, body: Buffer) {
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

async function post(request: import("@playwright/test").APIRequestContext, path: string, payload: unknown) {
  const body = Buffer.from(JSON.stringify(payload));
  const res = await request.post(`${apiBase}${path}`, { data: body, headers: signedHeaders("POST", path, body) });
  expect(res.status(), await res.text()).toBeLessThan(300);
}

test("los eventos de noticias muestran En cartera / En watchlist", async ({ page, request }) => {
  const marker = randomUUID().slice(0, 8);
  await post(request, "/api/portfolio/transactions", {
    ticker: "COST", action: "buy", quantity: 1, price: 900, trade_date: "2026-01-15", currency: "USD", fees: 0,
  });
  await post(request, "/api/watchlist", { symbol: "NFLX" });
  await post(request, "/api/news/ingest", {
    items: [
      // URL única por marcador: una URL fija hacía que el REINTENTO de la
      // spec re-ingiriera la misma URL con marcador nuevo y la dedup por URL
      // la saltara — la fila esperada nunca aparecía en el reintento.
      { ticker: "COST", title: `COST expands warehouses ${marker}`, text: "COST announced new warehouses.", source: "e2e", url: `https://e2e.invalid/cost-${marker}` },
      { ticker: "NFLX", title: `NFLX raises prices ${marker}`, text: "NFLX announced a price change.", source: "e2e", url: `https://e2e.invalid/nflx-${marker}` },
    ],
  });

  // Movers: el universo se calcula desde market_prices (global) de la BD
  // local. Las companias se provisionan por la via real (POST firmado
  // /api/companies/ensure) y los cierres los escribe el fixture del test
  // directamente en el sqlite local del backend (sin endpoint de
  // aplicacion): COST sube (+10%) y NFLX baja (-10%).
  await post(request, "/api/companies/ensure", { ticker: "COST", name: "Costco Wholesale" });
  await post(request, "/api/companies/ensure", { ticker: "NFLX", name: "Netflix" });
  // Fuente "yfinance": la unica que cuenta como cierre oficial en movers.
  // Volumenes liquidos: el suelo de liquidez de los rankings (cierre >= 5 y
  // negociacion cierre x volumen >= 1 M) expulsa semillas con volumen de juguete.
  seedMarketPrices("COST", [
    { date: "2026-09-24", close: 100, volume: 2_000_000 },
    { date: "2026-09-25", close: 110, volume: 2_000_000 },
  ], "yfinance");
  seedMarketPrices("NFLX", [
    { date: "2026-09-24", close: 100, volume: 3_000_000 },
    { date: "2026-09-25", close: 90, volume: 3_000_000 },
  ], "yfinance");

  await page.goto("/research/news");
  await expect(page.getByRole("heading", { name: "Eventos de noticias", level: 1 })).toBeVisible({ timeout: 60_000 });

  // La semilla va por API firmada directa al backend: la caché server-side
  // del frontend (memoryTTL ~15s sobre watchlist/posiciones) no se entera
  // hasta expirar. toPass + reload cubre esa ventana (mismo patrón que la
  // caché de movers) sin depender de timing.
  const mobile = (page.viewportSize()?.width ?? 1440) < 768;
  const newsRows = mobile ? page.getByRole("list", { name: "Eventos de noticias" }).getByRole("listitem") : page.getByRole("row");
  const costRow = newsRows.filter({ hasText: `COST expands warehouses ${marker}` });
  const nflxRow = newsRows.filter({ hasText: `NFLX raises prices ${marker}` });
  await expect(async () => {
    await page.reload();
    await expect(costRow.getByText("En cartera", { exact: true })).toBeVisible();
    await expect(costRow.getByText("En watchlist", { exact: true })).toHaveCount(0);
    await expect(nflxRow.getByText("En watchlist", { exact: true })).toBeVisible();
    await expect(nflxRow.getByText("En cartera", { exact: true })).toHaveCount(0);
  }).toPass({ intervals: [5_000, 10_000, 15_000], timeout: 45_000 });

  await page.screenshot({ path: `test-results/ticker-badges-news-${page.viewportSize()?.width}.png` });

  // La cache de movers es de 45s en el servidor de frontend: si otro test
  // la calento antes de la semilla, recargamos hasta que expire.
  await page.goto("/screener?vista=subidas");
  await expect(page.getByRole("heading", { name: "Explorar acciones", level: 1 })).toBeVisible({ timeout: 60_000 });
  await expect(async () => {
    await page.reload();
    const costMover = page.getByLabel("Mayores subidas").getByRole("row", { name: /COST/ });
    await expect(costMover.getByText("En cartera", { exact: true })).toBeVisible();
  }).toPass({ timeout: 70_000, intervals: [5_000, 10_000, 15_000] });
  await page.goto("/screener?vista=bajadas");
  await expect(async () => {
    await page.reload();
    const nflxMover = page.getByLabel("Mayores bajadas").getByRole("row", { name: /NFLX/ });
    await expect(nflxMover.getByText("En watchlist", { exact: true })).toBeVisible();
  }).toPass({ timeout: 70_000, intervals: [5_000, 10_000, 15_000] });
  await page.screenshot({ path: "test-results/ticker-badges-movers.png" });
});
