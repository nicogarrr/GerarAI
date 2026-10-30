import { expect, test, type Page } from "@playwright/test";

const runUiE2E = process.env.E2E_UI_RUN === "1";

// iPhone 14 viewport: 390x844 con táctil.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

async function expectNoPageOverflow(page: Page) {
  const overflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(
    overflow.scrollWidth,
    `overflow horizontal: scrollWidth=${overflow.scrollWidth} > innerWidth=${overflow.innerWidth} en ${page.url()}`,
  ).toBeLessThanOrEqual(overflow.innerWidth + 1);
}

async function expectPageLoaded(page: Page) {
  // La ruta carga: hay contenido principal y no hay pantalla de error 500.
  await expect(page.locator("main, body").first()).toBeVisible();
  await expect(page.getByText(/Application error|Something went wrong/i)).toHaveCount(0);
}

// Toda ruta del nav principal (+ /screener singular, cubierto por los specs
// investor-*) debe cargar a 390px sin overflow horizontal de página.
const NAV_ROUTES: { path: string; heading?: string }[] = [
  // `/` es la landing pública; el dashboard autenticado vive en `/inicio`.
  { path: "/" },
  { path: "/inicio" },
  { path: "/discover", heading: "Descubrir" },
  { path: "/portfolio" },
  { path: "/research" },
  { path: "/knowledge" },
  { path: "/search" },
  { path: "/screeners" },
  { path: "/screener", heading: "Explorar acciones" },
  { path: "/watchlist", heading: "Watchlist" },
  { path: "/screener?vista=subidas", heading: "Explorar acciones" },
  { path: "/propicks" },
  { path: "/alerts", heading: "Alertas" },
  { path: "/security", heading: "Seguridad" },
  { path: "/research/MSFT", heading: "MSFT" },
];

// Ancho de tablet portrait (768x1024 -> viewport 700px): cae entre `sm` (640)
// y `md` (768), la franja donde antes no existia ninguna navegacion primaria
// (el trigger era `sm:hidden` y el sidebar `md:flex`).
test.describe("navegación sin huecos de breakpoint", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test.use({ viewport: { width: 700, height: 900 } });

  test("a 700px hay menú de navegación accesible", async ({ page }) => {
    await page.goto("/alerts");
    const trigger = page.getByRole("button", { name: "Abrir menú de navegación" });
    await expect(trigger).toBeVisible();
    await trigger.click();
    await expect(page.getByRole("dialog", { name: "Menú de navegación" })).toBeVisible();
    // El drawer lleva el árbol completo, incluidas las secciones con hijos.
    await expect(page.getByRole("dialog", { name: "Menú de navegación" }).getByRole("link", { name: "Descubrir", exact: true })).toBeVisible();
    await expect(page.getByRole("dialog", { name: "Menú de navegación" }).getByRole("link", { name: "Biblioteca", exact: true })).toBeVisible();
  });
});

test.describe("mobile nav sin overflow horizontal", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  for (const route of NAV_ROUTES) {
    test(`${route.path} carga sin overflow a 390px`, async ({ page }) => {
      await page.goto(route.path);
      await expectPageLoaded(page);
      if (route.heading) {
        await expect(
          page.getByRole("heading", { name: route.heading, level: 1 }),
        ).toBeVisible();
      }
      await expectNoPageOverflow(page);
    });
  }
});
