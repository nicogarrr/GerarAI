import { expect, test } from "@playwright/test";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { E2E_UI_BACKEND_URL } from "./fixtures/e2e-env";

// Quick win UX 2: los muros de metodología quedan colapsados en un
// desplegable nativo, cerrado por defecto, y se expanden al tocarlo.
// Capturas con RENDER REAL (semilla de posiciones firmada, mismo patrón que
// f339-fab-rest-proof): una captura de BackendOffline no valida nada aquí.
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

async function seedPositions(request: import("@playwright/test").APIRequestContext) {
  // Tickers sinteticos exclusivos de esta spec: el tenant e2e es
  // compartido y comprar COST/NFLX aqui convertia esos tickers en
  // «En cartera» para la spec de badges (colision de semillas).
  const seeds = [
    { ticker: "E2EMD1", quantity: 5, price: 900 },
    { ticker: "E2EMD2", quantity: 4, price: 700 },
    { ticker: "E2EMD3", quantity: 6, price: 250 },
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
}

test("propicks abre con el contenido y la metodología colapsada (desktop)", async ({ page }) => {
  await page.goto("/propicks");

  await expect(page.getByRole("heading", { name: "ProPicks IA", level: 1 })).toBeVisible();

  const wall = page.getByText(/El embudo v1 puntúa cada categoría/);
  await expect(wall).toBeHidden();

  await page.screenshot({ path: "test-results/methodology-collapsed.png" });

  await page.getByText("Metodología y límites").click();
  await expect(wall).toBeVisible();
  await page.screenshot({ path: "test-results/methodology-expanded.png" });
});

test("propicks colapsada en móvil: la primera pantalla ya no es el muro", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/propicks");

  await expect(page.getByRole("heading", { name: "ProPicks IA", level: 1 })).toBeVisible();
  await expect(page.getByText(/El embudo v1 puntúa cada categoría/)).toBeHidden();
  await page.screenshot({ path: "test-results/methodology-propicks-mobile.png" });
});

test("/risk con alcance y límites colapsados (móvil y 768)", async ({ page, request }) => {
  await seedPositions(request);
  for (const [name, viewport] of [
    ["mobile", { width: 390, height: 844 }],
    ["768", { width: 768, height: 1024 }],
  ] as const) {
    await page.setViewportSize(viewport);
    await page.goto("/risk");

    // Sin render real no hay prueba: el test falla, no captura un fallback.
    await expect(page.getByRole("heading", { name: "Exposiciones de cartera", level: 1 })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText(/Esta página no calcula volatilidad/)).toBeHidden();
    await expect(page.getByText("Alcance y límites")).toBeVisible();
    await page.screenshot({ path: `test-results/methodology-risk-${name}.png` });
  }
});

test("/portfolio Resumen sin frase de arquitectura (móvil y 768)", async ({ page, request }) => {
  await seedPositions(request);
  for (const [name, viewport] of [
    ["mobile", { width: 390, height: 844 }],
    ["768", { width: 768, height: 1024 }],
  ] as const) {
    await page.setViewportSize(viewport);
    await page.goto("/portfolio");

    await expect(page.getByRole("heading", { name: "Resumen", level: 1 })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("Riesgo y exposiciones, en detalle:")).toBeVisible();
    await expect(page.getByText(/están fuera de la cartera: en su propia/)).toHaveCount(0);
    await page.screenshot({ path: `test-results/methodology-portfolio-${name}.png` });
  }
});
