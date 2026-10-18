import { expect, test } from "@playwright/test";

// Bug (Nico, 2026-10-19): cada clic en una pestaña de la ficha
// (/research/MSFT?view=...) devolvía al usuario al inicio de la página y la
// transición parecía un refresco. Debe quedarse donde está y cambiar solo el
// contenido. Este spec mide el salto en px antes y después del clic: con el
// bug `después` era 0; con el fix coincide con `antes` (o con el tope de
// scroll de la vista si ésta es más baja).
test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1 to run browser tests.");

const SCROLL_PX = 300;

async function medirSalto(
  page: import("@playwright/test").Page,
  pulsar: () => Promise<void>,
  urlEsperada: RegExp,
) {
  await page.evaluate((y) => window.scrollTo(0, y), SCROLL_PX);
  const antes = await page.evaluate(() => window.scrollY);
  expect(antes).toBeGreaterThan(0);
  await pulsar();
  await expect(page).toHaveURL(urlEsperada);
  // La vista nueva renderiza en servidor: espera a que llegue contenido.
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  const despues = await page.evaluate(() => ({
    y: window.scrollY,
    max: document.documentElement.scrollHeight - window.innerHeight,
  }));
  const esperado = Math.min(antes, despues.max);
  console.log(`scroll: antes=${Math.round(antes)}px despues=${Math.round(despues.y)}px tope=${Math.round(despues.max)}px`);
  expect(despues.y, `salto de scroll: antes=${Math.round(antes)}px, después=${Math.round(despues.y)}px`).toBe(esperado);
  if (despues.max > 0) expect(despues.y).toBeGreaterThan(0);
}

test("ficha: las pestañas de módulo conservan la posición de scroll (desktop)", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/research/MSFT");
  await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
  await medirSalto(
    page,
    () => page.getByRole("navigation", { name: /Módulos de/ }).getByRole("link", { name: "Tesis", exact: true }).click(),
    /\/research\/MSFT\?view=thesis/,
  );
});

test("ficha: los 3 pasos conservan la posición de scroll (móvil)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/research/MSFT?view=moat");
  await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
  await medirSalto(
    page,
    () => page.getByRole("navigation", { name: "Etapas del research", exact: true }).getByRole("link", { name: "2 · Valorar", exact: true }).click(),
    /\/research\/MSFT\?view=valorar/,
  );
});

test("biblioteca: las pestañas conservan la posición de scroll", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 600 });
  await page.goto("/knowledge");
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  await medirSalto(
    page,
    () => page.getByRole("tab", { name: "Subir", exact: true }).click(),
    /\/knowledge\?tab=subir/,
  );
});
