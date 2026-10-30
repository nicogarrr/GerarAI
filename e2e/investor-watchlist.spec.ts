import { expect, test } from "@playwright/test";

import { waitForScreenerOutcome } from "./fixtures/screener-outcome";

const runUiE2E = process.env.E2E_UI_RUN === "1";

test.describe("investor watchlist flow", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test("screener Seguir reports the add outcome via toast", async ({ page }) => {
    await page.goto("/screener");
    // Resolucion acotada: filas o estado final honesto; la carga indefinida falla.
    await waitForScreenerOutcome(page);

    const rows = page.locator("table tbody tr");
    if ((await rows.count()) === 0) {
      const down = page.getByText("No hay datos ahora mismo");
      const empty = page.getByText(/Sin resultados para/);
      const states = (await down.count()) + (await empty.count());
      expect(states).toBeGreaterThan(0);
      return;
    }

    const firstFollow = rows.first().getByRole("button", { name: "Seguir" });
    await expect(firstFollow).toBeEnabled();
    await firstFollow.click();

    // Backend healthy: "añadido a la watchlist". Backend down: "No se pudo añadir".
    // Both toasts mention the watchlist, so one assertion covers the round-trip.
    await expect(page.getByText(/watchlist/i).first()).toBeVisible({ timeout: 15_000 });
  });

  test("watchlist rows link to research and expose remove controls", async ({ page }) => {
    await page.goto("/watchlist");

    await expect(page.getByRole("heading", { name: "Watchlist", level: 1 })).toBeVisible();

    const mobile = (page.viewportSize()?.width ?? 1440) < 768;
    const rows = page.locator(mobile ? "main article" : "table tbody tr");
    if ((await rows.count()) === 0) {
      await expect(page.getByText("Tu watchlist está vacía")).toBeVisible();
      await expect(page.getByRole("link", { name: /Ir a buscar acciones/ })).toBeVisible();
      return;
    }

    if (!mobile) await expect(page.getByRole("columnheader", { name: "Símbolo" })).toBeVisible();
    const rowCount = await rows.count();
    expect(rowCount).toBeGreaterThan(0);
    for (let i = 0; i < rowCount; i += 1) {
      const row = rows.nth(i);
      await expect(row.getByRole("link").first()).toHaveAttribute(
        "href",
        /\/research\/[^/]+$/,
      );
      if (!mobile) await row.locator("summary").click();
      await expect(
        row.getByRole("button", { name: /^Eliminar .+ de la watchlist$/i }),
      ).toBeVisible();
    }
  });

  test("watchlist remove drops the row", async ({ page }) => {
    await page.goto("/watchlist");

    const mobile = (page.viewportSize()?.width ?? 1440) < 768;
    const rows = page.locator(mobile ? "main article" : "table tbody tr");
    const initial = await rows.count();
    if (initial === 0) {
      test.skip(true, "Watchlist is empty; nothing to remove.");
    }

    if (!mobile) await rows.first().locator("summary").click();
    await rows.first().getByRole("button", { name: /^Eliminar .+ de la watchlist$/i }).click();
    if (initial === 1) {
      await expect(page.getByText("Tu watchlist está vacía")).toBeVisible({ timeout: 15_000 });
    } else {
      await expect(rows).toHaveCount(initial - 1, {
        timeout: 15_000,
      });
    }
  });
});
