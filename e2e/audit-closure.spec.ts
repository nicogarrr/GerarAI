import { expect, test } from "@playwright/test";

const runUiE2E = process.env.E2E_UI_RUN === "1";

/**
 * Cierre de flujos a medias (auditoría verificada): cada punto con su
 * superficie visible. Gated como el resto de e2e UI (E2E_UI_RUN=1).
 */
test.describe("audit closure flows", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test("screener shows engine panel with offline fallback note", async ({ page }) => {
    await page.goto("/screener");
    await expect(page.getByRole("heading", { name: "Mercado", level: 1 })).toBeVisible();
    await expect(page.getByText("Motor de análisis", { exact: true })).toBeVisible();
    // Motor caído (fallback Finnhub) o motor con filtros: uno de los dos estados honestos.
    const fallback = page.getByText("motor de filtros no disponible");
    const empty = page.getByText("El motor de análisis responde, pero no hay filtros guardados");
    const filters = page.locator('a[href^="/screeners/"]');
    const states = (await fallback.count()) + (await empty.count()) + (await filters.count());
    expect(states).toBeGreaterThan(0);
  });

  test("taxes exposes year selector and regenerate", async ({ page }) => {
    await page.goto("/taxes");
    await expect(page.getByRole("heading", { name: "Impuestos", level: 1 })).toBeVisible();
    await expect(page.getByLabel("Ejercicio")).toBeVisible();
    await expect(page.getByRole("button", { name: /Regenerar/ })).toBeVisible();
  });

  test("alerts shows engine evaluation state", async ({ page }) => {
    await page.goto("/alerts");
    await expect(page.getByRole("heading", { name: "Alertas", level: 1 })).toBeVisible();
    // Espera a que el manager cliente termine de cargar antes de contar estados.
    // Suspense puede conservar un fallback oculto junto al loader cliente.
    // Espera todos los loaders visibles, sin elegir uno ni omitir estados.
    await expect(page.getByText("Cargando alertas...", { exact: true }).filter({ visible: true })).toHaveCount(0, { timeout: 30000 });
    // Guía Telegram (si falta config) o estado del motor por regla.
    const guide = page.getByText("Telegram sin configurar");
    const engineLine = page.getByText(/Motor: /);
    const empty = page.getByText("No tienes alertas configuradas");
    const states = (await guide.count()) + (await engineLine.count()) + (await empty.count());
    expect(states).toBeGreaterThan(0);
  });

  test("insider no longer shows monitor telemetry badge nor debug notify button", async ({ page }) => {
    await page.goto("/insider?ticker=AAPL");
    await expect(page.getByRole("heading", { name: "Señales Insider", level: 1 })).toBeVisible();
    // La telemetría del monitor (badge con contador) se retiró a propósito
    // (insider-degraded-honesty-guard): no debe volver a pintarse.
    await expect(page.getByText(/Monitor cada 15 min · \d+/)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Evaluar aviso Telegram ahora" })).toHaveCount(0);
  });

  test("research thesis exposes debate and approve controls", async ({ page }) => {
    await page.goto("/research/AAPL?view=thesis");
    const debate = page.getByText("Debate bull/bear");
    const approve = page.getByRole("button", { name: "Aprobar tesis" });
    // Con backend caído la página muestra BackendOffline; sin tesis muestra
    // el vacío honesto: en ambos casos no se exige el debate.
    const offline = page.getByText(/backend/i);
    const noThesis = page.getByText("Aún no existe ninguna tesis");
    const noThesis2 = page.getByText("Aún no se ha generado ninguna tesis");
    const noResearch = page.getByText(
      // F286: fuera del master la ficha ya no es «Research aún no generado»
      // sino uno de los tres estados honestos sin CTA.
      /Research aún no generado|todavía no tiene research|Identidad del ticker no verificada|No encontramos este ticker|No pudimos comprobar este ticker/,
    );
    if ((await offline.count()) > 0 || (await noThesis.count()) > 0 || (await noThesis2.count()) > 0 || (await noResearch.count()) > 0) return;
    await expect(debate).toBeVisible();
    await expect(approve).toBeVisible();
    await expect(page.getByRole("button", { name: /debate/i }).first()).toBeVisible();
  });

  test("la ficha no tiene chat propio: el campo abre el Cerebro", async ({ page }) => {
    await page.goto("/research/AAPL?view=chat");
    const field = page.getByLabel("Pregunta sobre AAPL");
    const noResearch = page.getByText(
      /Research aún no generado|todavía no tiene research|Identidad del ticker no verificada|No encontramos este ticker|No pudimos comprobar este ticker|backend/i,
    );
    if ((await field.count()) === 0) {
      expect(await noResearch.count()).toBeGreaterThan(0);
      return;
    }
    await field.fill("deuda nivel");
    await page.getByRole("button", { name: "Preguntar", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
  });

});
