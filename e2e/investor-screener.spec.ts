import { expect, test } from "@playwright/test";

import { waitForScreenerOutcome } from "./fixtures/screener-outcome";

const runUiE2E = process.env.E2E_UI_RUN === "1";

test.describe("investor screener flow", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test("screener table renders one Seguir button per row", async ({ page }) => {
    await page.goto("/screener");
    // Resolucion acotada: filas o estado final honesto; la carga indefinida falla.
    await waitForScreenerOutcome(page);

    await expect(page.getByRole("heading", { name: "Explorar acciones", level: 1 })).toBeVisible();
    // El sector se elige con un <select> accesible (SectorSelect), ya no con chips-enlace.
    await expect(page.getByLabel("Filtrar por sector")).toBeVisible();

    const rows = page.locator("table tbody tr");
    if ((await rows.count()) === 0) {
      // Backend caído (reintentar) o filtro sin resultados: ambas variantes honestas.
      const down = page.getByText("No hay datos ahora mismo");
      const empty = page.getByText(/Sin resultados para/);
      const states = (await down.count()) + (await empty.count());
      expect(states).toBeGreaterThan(0);
      return;
    }

    await expect(page.getByRole("columnheader", { name: "Seguir" })).toBeVisible();
    const rowCount = await rows.count();
    expect(rowCount).toBeGreaterThan(0);
    for (let i = 0; i < rowCount; i += 1) {
      const followButton = rows.nth(i).getByRole("button", { name: "Seguir" });
      await expect(followButton).toBeVisible();
      await expect(followButton).toBeEnabled();
    }
    // Tickers link out to their research page.
    await expect(rows.first().locator("td").first().getByRole("link")).toHaveAttribute(
      "href",
      /\/research\//,
    );
  });

  test("propicks cards expose Seguir per pick when picks render", async ({ page }) => {
    await page.goto("/propicks");

    await expect(page.getByRole("heading", { name: "ProPicks IA", level: 1 })).toBeVisible();

    const followButtons = page.getByRole("button", { name: "Seguir" });
    if ((await followButtons.count()) === 0) {
      // AI picks not generated in this environment; the shell must still render.
      await expect(page.getByRole("heading", { name: "ProPicks IA", exact: true })).toBeVisible();
      return;
    }
    await expect(followButtons.first()).toBeVisible();
    await expect(followButtons.first()).toBeEnabled();
  });
});
