import { expect, test } from "@playwright/test";

const runUiE2E = process.env.E2E_UI_RUN === "1";

// La ficha tenia tres capas de navegacion encima de la cotizacion (subnav del
// hub, flecha «Research» y pestañas de la ficha) y en movil el precio quedaba
// casi al final del primer viewport. Geometria real: jsdom no tiene layout.
for (const viewport of [
  { width: 390, height: 844 },
  { width: 1280, height: 900 },
]) {
  test(`ficha MSFT ${viewport.width}px: sin subnav del hub y cotizacion en el primer viewport`, async ({ page }) => {
    test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");
    await page.setViewportSize(viewport);
    await page.goto("/research/MSFT");
    await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Herramientas de la sección" })).toHaveCount(0);
    await expect(page.getByRole("navigation", { name: "Secciones de la empresa" })).toBeVisible();

    const quote = page.getByTestId("company-header-quote");
    await expect(quote).toBeVisible();
    const box = await quote.boundingBox();
    expect(box, "la cotizacion se pinta").not.toBeNull();
    // El precio arranca en el 60 % superior del primer viewport (antes: ~66 %
    // en 390x844 y ~63 % en 1280x900, con el subnav y la flecha duplicados).
    expect(box!.y).toBeLessThanOrEqual(viewport.height * 0.6);

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
}

test("una herramienta del hub conserva su subnav con la actual marcada", async ({ page }) => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/research/news");
  const nav = page.getByRole("navigation", { name: "Herramientas de la sección" });
  await expect(nav).toBeVisible();
  await expect(nav.getByRole("link", { name: "Noticias", exact: true })).toHaveAttribute("aria-current", "page");
});
