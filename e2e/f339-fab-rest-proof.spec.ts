import { expect, test } from "@playwright/test";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { seedMarketPrices } from "./fixtures/market-prices";
import { E2E_UI_BACKEND_URL } from "./fixtures/e2e-env";

// F339: a 390px la acción Cerebro vive en BottomNav; el FAB desktop
// queda oculto y no puede tapar la leyenda del donut.
test.use({
  viewport: { width: 390, height: 844 },
  hasTouch: true,
  isMobile: true,
});

// A nivel de archivo: en el job de API (sin E2E_UI_RUN) el fixture `page`
// lanzaría el navegador antes de cualquier skip dentro del cuerpo del test.
test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1 to run browser tests.");

const apiSecret = process.env.RESEARCH_AUTH_SECRET ?? "cavaai-e2e-research-secret-at-least-32-characters";
const apiUser = "e2e-browser-user"; // el bypass E2E firma tenant=user.id
const apiBase = E2E_UI_BACKEND_URL;

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

test("F339: móvil usa acción inline y nunca superpone el FAB a la leyenda", async ({ page, request }) => {

  // Semilla: 6 posiciones para que el donut tenga leyenda real.
  const seeds = [
    { ticker: "GOOGL", quantity: 10, price: 150 },
    { ticker: "AAPL", quantity: 8, price: 170 },
    { ticker: "MSFT", quantity: 3, price: 400 },
    { ticker: "V", quantity: 4, price: 250 },
    { ticker: "AMZN", quantity: 5, price: 180 },
    { ticker: "JPM", quantity: 6, price: 200 },
  ];
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

  // Sin precios ni FX el backend devuelve market_value_base=null y el donut
  // se abstiene (honesto): la leyenda necesita valores reales sembrados.
  // Dos cierres por ticker: _common_sessions exige que la sesion anterior
  // pase un suelo de cobertura (mediana/2); con una sola fecha por ticker el
  // 2026-09-24 quedaba por debajo y los rankings de movers salian vacios
  // (ticker-badges siembra COST/NFLX en 09-24 y 09-25).
  for (const s of seeds) {
    seedMarketPrices(s.ticker, [
      { date: "2026-09-24", close: s.price },
      { date: "2026-09-25", close: s.price },
    ]);
  }
  // FX via API firmada: el upsert revaloriza TODAS las posiciones
  // (rebuild_position), asi market_value_base queda calculado con los
  // precios sembrados. Sembrar la fila en sqlite no basta: /positions lee
  // columnas materializadas, no revalua en lectura.
  const fxBody = Buffer.from(JSON.stringify({
    base_currency: "EUR", quote_currency: "USD", rate: 0.86,
    rate_date: "2026-01-10", source: "e2e-fixture",
  }));
  const fxRes = await request.post(`${apiBase}/api/portfolio/fx-rates`, {
    data: fxBody, headers: signedHeaders("POST", "/api/portfolio/fx-rates", fxBody),
  });
  expect(fxRes.status(), await fxRes.text()).toBeLessThan(300);

  await page.goto("/portfolio");
  const legend = page.locator("#portfolio-allocation-legend");
  await expect(legend).toBeVisible({ timeout: 60_000 });
  // Mobile uses the inline BottomNav action, not a floating button.
  // The desktop FAB must remain absent while the legend is in view or at rest.
  const fab = page.locator('button[aria-label="Abrir el cerebro"].fixed');
  const brainAction = page.getByRole('navigation', { name: 'Navegación inferior' }).getByRole('button', { name: 'Abrir el cerebro', exact: true });
  await expect(fab).toBeHidden();
  await expect(brainAction).toBeVisible();
  await legend.scrollIntoViewIfNeeded();
  await expect(fab).toBeHidden();
  await page.screenshot({ path: "test-results/f339-mobile-inline-brain.png" });
  await page.getByRole("tab", { name: "Posiciones", exact: true }).click();
  await expect(fab).toBeHidden();
  await page.getByRole("tab", { name: "Resumen", exact: true }).click();
  await expect(legend).toBeVisible();
  await expect(fab).toBeHidden();
});
