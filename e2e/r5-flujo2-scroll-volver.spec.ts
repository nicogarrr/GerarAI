import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { E2E_UI_BACKEND_URL } from "./fixtures/e2e-env";

/**
 * Recorrido real (auditoría de flujo r5, 11-nov): se baja por la ficha en la
 * pestaña Valoración, se pulsa el enlace al Informe del contenido y se
 * vuelve. Medido en un `next build` a 1440 px (NVDA): desde 1600 px, el atrás
 * del navegador dejaba la ficha en 2469 px. Ahora se vuelve a la posición del
 * usuario (o al tope si la página ya no llega).
 */
const runUiE2E = process.env.E2E_UI_RUN === "1";
const apiSecret = process.env.RESEARCH_AUTH_SECRET ?? "cavaai-e2e-research-secret-at-least-32-characters";
const apiUser = "e2e-browser-user";

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

async function post(request: APIRequestContext, path: string, payload: unknown) {
  const body = Buffer.from(JSON.stringify(payload));
  const res = await request.post(`${E2E_UI_BACKEND_URL}${path}`, { data: body, headers: signedHeaders("POST", path, body) });
  expect(res.status(), await res.text()).toBeLessThan(300);
}

/**
 * Baja por la ficha hasta el enlace al Informe del contenido (no el del menú
 * «Más acciones», que está arriba) y devuelve el scroll desde el que se pulsa.
 */
async function scrollToContentReportLink(page: Page) {
  const link = page.locator('main a[href$="/informe"]').first();
  await link.scrollIntoViewIfNeeded();
  await page.mouse.move(200, 300);
  await page.mouse.wheel(0, 120);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  let last = -1;
  await expect.poll(async () => {
    const y = await page.evaluate(() => Math.round(window.scrollY));
    const settled = y === last;
    last = y;
    return settled;
  }).toBe(true);
  await link.scrollIntoViewIfNeeded();
  return { link, before: await page.evaluate(() => Math.round(window.scrollY)) };
}

/** La posición vuelve a la del usuario (o al tope si la página es más corta). */
async function expectBackAt(page: Page, before: number) {
  await expect.poll(async () => {
    const { y, max } = await page.evaluate(() => ({
      y: Math.round(window.scrollY),
      max: Math.round(document.documentElement.scrollHeight - window.innerHeight),
    }));
    return Math.abs(y - Math.min(before, max)) <= 2 && y > 0;
  }, { timeout: 15_000, message: `scroll esperado ≈ ${before}px` }).toBe(true);
}

for (const [label, viewport] of [["móvil 390", { width: 390, height: 844 }], ["PC 1440", { width: 1440, height: 900 }]] as const) {
  test.describe(`scroll al volver a la ficha (${label})`, () => {
    test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");
    test.use({ viewport });

    test.beforeEach(async ({ request }) => {
      await post(request, "/api/companies/ensure", { ticker: "MSFT", name: "Microsoft" });
    });

    test("atrás del navegador desde el Informe vuelve a donde estabas", async ({ page }) => {
      await page.goto("/research/MSFT?view=valoracion");
      await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
      const { link, before } = await scrollToContentReportLink(page);
      expect(before).toBeGreaterThan(0);
      await link.click();
      await page.waitForURL(/\/research\/MSFT\/informe/);
      await expect(page.locator("h1").first()).toBeVisible();
      await page.goBack();
      await page.waitForURL(/\/research\/MSFT\?view=valoracion/);
      await expectBackAt(page, before);
    });

    test("«← Volver a la ficha» del Informe vuelve a la pestaña y a donde estabas", async ({ page }) => {
      await page.goto("/research/MSFT?view=valoracion");
      await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
      const { link, before } = await scrollToContentReportLink(page);
      await link.click();
      await page.waitForURL(/\/research\/MSFT\/informe/);
      const back = page.getByRole("link", { name: "← Volver a la ficha" });
      await expect(back).toHaveAttribute("data-back-mode", "history");
      await back.click();
      await page.waitForURL(/\/research\/MSFT\?view=valoracion/);
      await expectBackAt(page, before);
    });
  });
}
