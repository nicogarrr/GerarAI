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
  destino: import("@playwright/test").Locator,
  urlEsperada: RegExp,
  layoutEstable?: import("@playwright/test").Locator,
) {
  // La cabecera de la ficha llega por streaming: el Suspense de la cotización
  // muestra un fallback y al resolverse lo sustituye la cotización. En modo
  // compacto el gráfico queda oculto; el wrapper de cotización visible indica
  // que el streaming terminó, sin depender del gráfico oculto. Medir `antes` con el fallback falseaba la
  // comparación: al crecer la cabecera, el anclaje de scroll del navegador
  // desplaza scrollY para mantener visible lo que el usuario ve (el salto de
  // ~487px en móvil / ~76px en desktop era ESO, no el clic), y `después`
  // reflejaba el layout definitivo. Esperando a que el layout sea el final,
  // `antes` y `después` se miden contra la misma página.
  if (layoutEstable) await expect(layoutEstable).toBeVisible();
  await page.evaluate((y) => window.scrollTo(0, y), SCROLL_PX);
  // Un usuario real pulsa la pestaña que VE. El hover provoca el mismo
  // scroll-into-view de Playwright que el clic, así `antes` se mide en la
  // posición desde la que se pulsa de verdad. Medir a 300px con la pestaña
  // fuera del viewport falseaba la comparación: el propio clic desplazaba
  // la página antes del pointerdown que captura ScrollPreserver, y la
  // posición restaurada (correcta) ya no coincidía con `antes`.
  await destino.hover();
  const antes = await page.evaluate(() => window.scrollY);
  expect(antes).toBeGreaterThan(0);
  await destino.click();
  await expect(page).toHaveURL(urlEsperada);
  // La vista nueva renderiza en servidor: espera a que llegue contenido.
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  // La cabecera vuelve a suspender al cambiar de vista: misma espera antes
  // de medir `después` para no capturar el fallback de streaming.
  if (layoutEstable) await expect(layoutEstable).toBeVisible();
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
    page.getByRole("navigation", { name: /Módulos de/ }).getByRole("link", { name: "Tesis", exact: true }),
    /\/research\/MSFT\?view=thesis/,
    page.getByTestId("company-header-quote"),
  );
});

test("ficha: los 3 pasos conservan la posición de scroll (móvil)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/research/MSFT?view=moat");
  await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
  await medirSalto(
    page,
    page.getByRole("navigation", { name: "Secciones de la empresa", exact: true }).getByRole("link", { name: "Finanzas", exact: true }),
    /\/research\/MSFT\?view=financials/,
    page.getByTestId("company-header-quote"),
  );
});

test("biblioteca: las pestañas conservan la posición de scroll", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 600 });
  await page.goto("/knowledge");
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  await medirSalto(
    page,
    page.getByRole("tab", { name: "Subir", exact: true }),
    /\/knowledge\?tab=subir/,
  );
});
