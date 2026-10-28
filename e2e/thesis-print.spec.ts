import { expect, test } from "@playwright/test";

const runUiE2E = process.env.E2E_UI_RUN === "1";
// Skip before the page fixture launches: the API-only job has no browser.
test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

// Impresion de la vista de lectura (Imprimir / guardar como PDF del navegador).
// La regla de impresion ocultaba todo <header>, tambien el del propio
// documento: el papel salia sin ticker, empresa, rating ni version. Con una
// tesis publicada en la base se comprueba la cabecera del articulo; sin ella
// (base vacia de CI) se comprueba el titulo del estado vacio.
test("la tesis impresa conserva su cabecera y no lleva chrome de la app", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/research/MSFT/tesis");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const hasArticle = (await page.getByText("Tesis de inversión", { exact: true }).count()) > 0;

  await page.emulateMedia({ media: "print" });
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  if (hasArticle) {
    await expect(page.getByText("Tesis de inversión", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "PDF" })).toBeHidden();
    // display:none saca los dos indices del arbol accesible: se localizan por atributo.
    const tocs = page.locator('nav[aria-label="Índice de la tesis"]');
    await expect(tocs).toHaveCount(2);
    for (const nav of await tocs.all()) {
      await expect(nav).toBeHidden();
    }
  }
  await expect(page.getByRole("button", { name: "Abrir el cerebro" })).toBeHidden();
  await expect(page.getByRole("navigation", { name: "Ruta de navegación" })).toBeHidden();
  const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(background).toBe("rgb(255, 255, 255)");
});
