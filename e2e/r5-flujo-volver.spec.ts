import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { E2E_UI_BACKEND_URL } from "./fixtures/e2e-env";
import { waitForHydration } from "./fixtures/wait-for-hydration";

/**
 * Recorrido real (auditoría r5-fa-flujo, 11-nov): ficha en una pestaña
 * `?view=` → subpágina del menú «Más acciones» → «← Volver». Antes el enlace
 * iba siempre a un padre fijo (/research o /research/T sin pestaña): se
 * perdía la vista, el scroll y se renderizaba la ficha entera otra vez; en la
 * app instalada del iPhone ese enlace es la única forma de volver.
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

async function openFromMenu(page: Page, name: RegExp) {
  await page.getByRole("button", { name: "Más acciones" }).first().click();
  await page.getByRole("link", { name }).first().click();
}

for (const [label, viewport] of [["móvil 390", { width: 390, height: 844 }], ["PC 1440", { width: 1440, height: 900 }]] as const) {
  test.describe(`flujo de vuelta (${label})`, () => {
    test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");
    test.use({ viewport });

    test.beforeEach(async ({ request }) => {
      await post(request, "/api/companies/ensure", { ticker: "MSFT", name: "Microsoft" });
      await post(request, "/api/watchlist", { symbol: "MSFT" });
    });

    test("insiders desde la pestaña Valoración: «Volver a MSFT» conserva la pestaña", async ({ page }) => {
      await page.goto("/research/MSFT?view=valoracion");
      await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
      await openFromMenu(page, /^Insiders$/);
      await page.waitForURL(/\/insider\?ticker=MSFT/);
      const back = page.getByRole("link", { name: "Volver a MSFT" });
      await expect(back).toHaveAttribute("data-back-mode", "history");
      await back.click();
      await page.waitForURL(/\/research\/MSFT\?view=valoracion/);
    });

    test("abierta directamente (enlace externo): «Volver a MSFT» va a la ficha", async ({ page }) => {
      await page.goto("/insider?ticker=MSFT");
      const back = page.getByRole("link", { name: "Volver a MSFT" });
      await expect(back).toHaveAttribute("href", "/research/MSFT");
      await expect(back).toHaveAttribute("data-back-mode", "link");
      await back.click();
      await page.waitForURL(/\/research\/MSFT$/);
    });

    test("watchlist → ficha → «Volver» vuelve a la watchlist en móvil", async ({ page }) => {
      test.skip(viewport.width >= 768, "El enlace de vuelta de la ficha solo se ve en móvil (en PC están las migas).");
      await page.goto("/watchlist");
      // Alcance declarado: navegación SPA YA hidratada. Sin esta espera el
      // clic podía caer antes de hidratar y ser una carga de documento
      // completa, que nace sin pila de in-app-history y pinta el fallback
      // «Research» en vez de «Volver» (rojo de main 2400440, móvil 390).
      // Ese camino queda cubierto por el test negativo siguiente.
      // waitForHydration es un waitForFunction dentro del timeout global del
      // test; los presupuestos de las aserciones (10 s) no cambian.
      await waitForHydration(page);
      // Observación del tipo de navegación: SPA no emite request «document».
      let documentNav = false;
      page.on("request", (req) => {
        if (req.resourceType() === "document" && /\/research\/MSFT/.test(req.url())) documentNav = true;
      });
      await page.getByRole("link", { name: /Ver análisis/ }).first().click();
      await page.waitForURL(/\/research\/MSFT/);
      expect(documentNav, "el test mide la navegación SPA; una carga de documento invalida la premisa").toBe(false);
      const back = page.getByRole("link", { name: "Volver" });
      await expect(back).toHaveAttribute("data-back-mode", "history");
      await back.click();
      await page.waitForURL(/\/watchlist/);
    });

    test("clic antes de hidratar: carga de documento y el enlace queda en su fallback «Research» (móvil)", async ({ page }) => {
      test.skip(viewport.width >= 768, "Mismo alcance móvil que el caso positivo.");
      // Prueba negativa del mecanismo del rojo de main 2400440: con los .js
      // retenidos (técnica de prehydration-mobile-open.spec.ts) el clic en
      // «Ver análisis» es una carga de documento completa; la pila de
      // in-app-history nace vacía en la ficha (Navigation API: solo entradas
      // observadas desde que arranca el JS) y el enlace de vuelta pinta su
      // fallback con data-back-mode="link". Que «Volver» sobreviva cargas
      // completas sería un cambio de producto aparte.
      let release!: () => void;
      const gate = new Promise<void>((resolve) => { release = resolve; });
      await page.route("**/_next/**/*.js*", async (route) => { await gate; await route.continue(); });
      let documentNav = false;
      page.on("request", (req) => {
        if (req.resourceType() === "document" && /\/research\/MSFT/.test(req.url())) documentNav = true;
      });
      try {
        await page.goto("/watchlist", { waitUntil: "commit" });
        const link = page.getByRole("link", { name: /Ver análisis/ }).first();
        await expect(link).toBeVisible();
        await Promise.all([
          // 'commit': con los .js retenidos el load del documento nuevo no
          // llega; commit basta para observar el request document.
          page.waitForURL(/\/research\/MSFT/, { waitUntil: "commit" }),
          link.click({ noWaitAfter: true }),
        ]);
        expect(documentNav, "clic pre-hidratación = carga de documento completa").toBe(true);
        release();
        // Acotado a main + data-back-mode: en main hay otro enlace
        // «Research» (subnav de búsqueda) y BottomNav tiene otro fuera.
        const back = page.getByRole("main").locator('a[data-back-mode="link"]');
        await expect(back).toHaveAttribute("href", /\/research$/);
        await expect(back).toHaveText(/^Research$/);
        await expect(page.getByRole("link", { name: "Volver" })).toHaveCount(0);
      } finally {
        release();
        await page.unrouteAll({ behavior: "ignoreErrors" });
      }
    });
  });
}
