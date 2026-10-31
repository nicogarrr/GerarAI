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
  // Resto de secciones del producto sin cobertura de overflow a 390px
  // (31-oct-2026). Cada heading sale del h1 real de la página (literal o
  // clave i18n es-ES resuelta en lib/i18n/messages/es/).
  // /calendar no va: redirige a /alerts (ya cubierta).
  { path: "/mercados", heading: "Mercados" },
  { path: "/insider", heading: "Señales insider" },
  { path: "/plan", heading: "Plan de inversión" },
  { path: "/risk", heading: "Exposiciones de cartera" },
  { path: "/temas", heading: "Temas" },
  { path: "/cuellos", heading: "Cuellos de botella" },
  { path: "/settings", heading: "Ajustes" },
  { path: "/paper-trading", heading: "Mi cuenta demo" },
  { path: "/macro-calendar", heading: "Calendario macro y 8-K" },
  { path: "/inversores", heading: "Inversores" },
  { path: "/knowledge-graph", heading: "Grafo de conocimiento" },
  { path: "/export", heading: "Exportación" },
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
      // 1. La navegación responde bien (un 404/500 también renderiza "algo").
      const response = await page.goto(route.path);
      expect(response, `${route.path}: sin respuesta del servidor`).not.toBeNull();
      expect(
        response!.status(),
        `${route.path}: status ${response!.status()} (se esperaba < 400)`,
      ).toBeLessThan(400);
      // 2. La ruta no redirige (a login, a /alerts, ...): seguimos donde pedimos.
      const expectedPath = route.path.split("?")[0];
      expect(
        new URL(page.url()).pathname,
        `${route.path}: redirigió a ${page.url()}`,
      ).toBe(expectedPath);
      // 3. Señal de contenido o estado final ANTES de medir: un overflow
      //    medido con la página a medio cargar es un falso verde.
      if (route.heading) {
        await expect(
          page.getByRole("heading", { name: route.heading, level: 1 }),
        ).toBeVisible();
      } else {
        await expectPageLoaded(page);
      }
      await expectNoPageOverflow(page);
    });
  }
});
