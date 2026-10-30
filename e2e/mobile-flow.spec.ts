import { expect, test, type Page } from "@playwright/test";

import { waitForScreenerOutcome } from "./fixtures/screener-outcome";

const runUiE2E = process.env.E2E_UI_RUN === "1";

// iPhone 14 viewport: 390x844 con táctil. Todo el flujo usa toques (tap),
// nunca click de ratón ni scroll horizontal de página.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

async function expectNoPageOverflow(page: Page, step: string) {
  const overflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(
    overflow.scrollWidth,
    `${step}: overflow horizontal scrollWidth=${overflow.scrollWidth} > innerWidth=${overflow.innerWidth}`,
  ).toBeLessThanOrEqual(overflow.innerWidth + 1);
}

test.describe("mobile flujo screener→watchlist→tesis→alerta solo con toques", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test("screener→seguir→watchlist→tesis→alerta sin scroll horizontal", async ({
    page,
  }) => {
    // 1. Screener carga sin overflow.
    await page.goto("/screener");
    await expect(page.getByRole("heading", { name: "Explorar acciones", level: 1 })).toBeVisible();
    // La carga de precios es asíncrona: sin esta espera acotada, el test
    // decidía "sin datos" antes de que la página pintara su estado final.
    await waitForScreenerOutcome(page);
    await expectNoPageOverflow(page, "screener");

    // 2. Seguir con toque: en móvil (<md) el screener renderiza cards con
    // FollowButton; la tabla es solo desktop (hidden). Por eso se buscan los
    // botones visibles, no las filas de la tabla.
    const followButtons = page.getByRole("button", { name: "Seguir" });
    if ((await followButtons.count()) === 0) {
      // Sin datos de mercado: el flujo no puede continuar, pero la
      // página degradada tampoco debe desbordar.
      const down = page.getByText("No hay datos ahora mismo");
      const empty = page.getByText(/Sin resultados para/);
      const states = (await down.count()) + (await empty.count());
      expect(states).toBeGreaterThan(0);
      await expectNoPageOverflow(page, "screener-vacio");
      return;
    }

    const firstFollow = followButtons.first();
    await expect(firstFollow).toBeVisible();
    await expect(firstFollow).toBeEnabled();
    await firstFollow.tap();
    // Toast de sonner confirma el alta (texto específico del toast para no
    // coincidir con el enlace "Watchlist" del nav desktop, oculto en móvil).
    await expect(
      page.getByText(/añadido a la watchlist|no se pudo añadir/i).first(),
    ).toBeVisible({ timeout: 15_000 });
    await expectNoPageOverflow(page, "tras-seguir");

    // 3. Ir a la watchlist tocando el menú hamburger móvil y el enlace
    // del drawer (el nav desktop está oculto en móvil).
    await page.getByRole("button", { name: "Abrir menú de navegación" }).tap();
    const drawer = page.getByRole("dialog", { name: "Menú de navegación" });
    await expect(drawer).toBeVisible();
    await expectNoPageOverflow(page, "drawer-nav");
    await drawer.getByRole("link", { name: "Watchlist" }).tap();
    await expect(page).toHaveURL(/\/watchlist/);
    await expect(page.getByRole("heading", { name: "Watchlist", level: 1 })).toBeVisible();
    await expectNoPageOverflow(page, "watchlist");

    // 4. Tocar el enlace a research de la primera card ("Ver análisis").
    const watchCards = page.locator("article", { hasText: "Ver análisis" });
    if ((await watchCards.count()) === 0) {
      await expect(page.getByText("Tu watchlist está vacía")).toBeVisible();
      await expectNoPageOverflow(page, "watchlist-vacia");
      return;
    }
    await watchCards.first().getByRole("link", { name: /Ver análisis/ }).tap();
    await expect(page).toHaveURL(/\/research\/[^/]+$/);
    await expectNoPageOverflow(page, "research");

    // 5. Crear alerta con toques: abrir el popover de la campana,
    // rellenar objetivo y tocar "+ Alerta".
    await page.getByRole("button", { name: "Alerta de precio" }).tap();
    const targetInput = page.getByPlaceholder("Precio objetivo $");
    await expect(targetInput).toBeVisible();
    await targetInput.tap();
    await targetInput.fill("250");
    await page.getByRole("button", { name: "+ Alerta" }).tap();
    // Backend sano: toast de alerta creada. Sin precio válido o backend
    // caído: mensaje de validación/error visible en la página. Textos del
    // toast de sonner, no del nav (el enlace "Alertas" está oculto en móvil).
    const outcome = page
      .getByText(/alerta creada|precio objetivo válido/i)
      .first();
    await expect(outcome).toBeVisible({ timeout: 15_000 });
    await expectNoPageOverflow(page, "tras-alerta");
  });
});
