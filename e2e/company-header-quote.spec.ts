import { expect, test } from "@playwright/test";

// Quick win UX 1: la cabecera de la ficha muestra precio + variación +
// gráfico técnico con el fixture E2E determinista, en desktop y móvil, y las
// capturas quedan en test-results como prueba píxel a píxel.
test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1 to run browser tests.");

// El precio aparece también en otras zonas de la ficha: las aserciones se
// acotan a la cabecera (data-testid) para no violar el modo estricto.
const header = (page: import("@playwright/test").Page) => page.getByTestId("company-header-quote");

test("cabecera de la ficha con precio, variación y gráfico técnico (desktop)", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/research/MSFT");

  await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
  await expect(header(page).getByText(/^336,56\sUS\$$/)).toBeVisible();
  // La variación USD se pinta como moneda con signo (exceptZero): «+2,34 US$».
  await expect(header(page).getByText(/^\+2,34\sUS\$ · \+0,70\s%$/)).toBeVisible();
  await expect(header(page).getByRole("figure", { name: /Evolución del precio/ })).toBeVisible();
  await expect(header(page).getByTestId("technical-reading")).toBeVisible();
  const strip = header(page).getByTestId('company-metric-strip');
  await expect(strip).toBeVisible();
  await expect(strip.getByText(/^334,20\sUS\$$/)).toBeVisible();
  await expect(strip.getByText('N/D', { exact: true })).toBeVisible();
  await expect(header(page).getByText('Fixture local · 17:00 (Madrid)', { exact: true })).toBeVisible();
  await header(page).getByText('Más detalle', { exact: true }).click();
  await expect(header(page).getByText(/^Sesión regular del 9 sept\.? 2026 · 17:00 \(Madrid\)$/)).toBeVisible();
  await page.screenshot({ path: "test-results/header-quote-desktop.png" });
});

test("cabecera de la ficha con precio, variación y gráfico técnico (móvil)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/research/MSFT");

  await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
  await expect(header(page).getByText(/^336,56\sUS\$$/)).toBeVisible();
  await expect(header(page).getByText("+0,70 %")).toBeVisible();
  await expect(header(page).getByRole("figure", { name: /Evolución del precio/ })).toBeVisible();
  await page.screenshot({ path: "test-results/header-quote-mobile.png" });
});

test("otras vistas también llevan la cotización en cabecera", async ({ page }) => {
  await page.goto("/research/MSFT?view=thesis");

  await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
  await expect(header(page).getByText(/^336,56\sUS\$$/)).toBeVisible();
});


test("quote unavailable never hides the company heading or chart structure", async ({ page }) => {
  await page.route('**/api/companies/MSFT/extended-quote', route => route.fulfill({ status: 502, json: { status: 'unavailable' } }));
  await page.goto('/research/MSFT');
  await expect(page.getByRole('heading', { name: 'MSFT', level: 1 })).toBeVisible();
  // Sin cotización, la cabecera cae al último cierre del gráfico, rotulado.
  await expect(header(page).getByText('Cotización en vivo no disponible ahora', { exact: false })).toBeVisible();
  await expect(header(page).getByText('Último cierre del gráfico', { exact: false })).toBeVisible();
  await expect(header(page).getByTestId('company-metric-strip')).toBeVisible();
  await expect(header(page).getByTestId('company-technical-chart')).toBeVisible();
});
