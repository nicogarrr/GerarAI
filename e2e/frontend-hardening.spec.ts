import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const runUiE2E = process.env.E2E_UI_RUN === "1";

function source(...parts: string[]): string {
  return readFileSync(resolve(process.cwd(), ...parts), "utf8");
}

test.describe("hardening frontend estático", () => {
  test("el shell raíz aporta skip-link y deja el landmark main a cada página", () => {
    const layout = source("app", "(root)", "layout.tsx");

    // El layout no envuelve a las páginas en otro <main>: cada página es la
    // dueña de su landmark, y el skip-link apunta al id que estas declaran.
    expect(layout).not.toContain("<main");
    expect(layout).toContain('href="#content"');
    expect(layout).toContain("Saltar al contenido");
    // La geometria del shell sale de variables CSS, no de 4rem/100vh sueltos.
    expect(layout).toContain("min-h-dvh");
  });

  test("el sidebar y el drawer comparten breakpoint de navegación", () => {
    const sidebar = source("components", "layout", "Sidebar.tsx");
    const mobileNav = source("components", "MobileNav.tsx");

    // Entre 640px y 767px no puede existir una ventana sin navegación.
    expect(sidebar).toContain("md:flex");
    expect(mobileNav).toContain("md:hidden");
    // La trampa de foco del drawer vive en un solo sitio.
    expect(mobileNav).toContain("querySelectorAll<HTMLElement>");
    expect(mobileNav).not.toContain("onDrawerKeyDown");
  });

  test("la pantalla de error no muestra el mensaje interno", () => {
    const errorBoundary = source("app", "(root)", "error.tsx");

    expect(errorBoundary).toContain('role="alert"');
    expect(errorBoundary).toContain("Se produjo un error inesperado");
    expect(errorBoundary).not.toMatch(/error\.message\s*\|\|/);
  });

  test("MutationForm y SelectField exponen estado pending y validación", () => {
    const mutationForm = source("components", "forms", "MutationForm.tsx");
    const selectField = source("components", "forms", "SelectField.tsx");

    expect(mutationForm).toContain("aria-busy={isPending}");
    expect(mutationForm).toContain("disabled={isPending}");
    expect(mutationForm).toContain('role="status"');
    expect(selectField).toContain("id={selectId}");
    expect(selectField).toContain("aria-required={required}");
    expect(selectField).toContain("aria-invalid={Boolean(error)}");
    expect(selectField).toContain("aria-describedby=");
  });

  test("los controles iconográficos y el fallo de búsqueda tienen semántica", () => {
    const mobileNav = source("components", "MobileNav.tsx");
    const searchCommand = source("components", "SearchCommandDialog.tsx");
    const portfolioChat = source("components", "brain", "GlobalBrain.tsx") + source("components", "brain", "GlobalBrainPanel.tsx");

    expect(mobileNav).toContain("closeButtonRef");
    expect(mobileNav).toContain("aria-labelledby=\"mobile-nav-title\"");
    expect(mobileNav).toContain('aria-label="Cerrar menú por fondo"');
    expect(mobileNav).toContain("querySelectorAll<HTMLElement>");
    expect(searchCommand).toContain("searchError");
    expect(searchCommand).toContain("No se pudo completar la búsqueda");
    expect(searchCommand).not.toMatch(/catch \(error: any\)[\s\S]*?setStocks\(\[\]\);[\s\S]*?\n\s*}/);
    expect(portfolioChat).toContain("Abrir el cerebro");
    expect(portfolioChat).toContain("aria-labelledby=\"global-brain-title\"");
  });
});

test.describe("hardening frontend en navegador", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");
  // Viewport movil: el hamburger solo existe <sm (sm:hidden); sin esto el
  // click del trigger hace timeout en el viewport desktop por defecto.
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("las páginas raíz exponen un único main", async ({ page }) => {
    await page.goto("/alerts");
    await expect(page.locator("main")).toHaveCount(1);
    // El skip-link existe y lleva al contenido (no hay #content roto).
    await expect(page.getByRole("link", { name: "Saltar al contenido" })).toHaveCount(1);
  });

  test("el menú móvil abre, enfoca y restaura el foco", async ({ page }) => {
    await page.goto("/alerts");
    const trigger = page.getByRole("button", { name: "Abrir menú de navegación" });
    await trigger.click();
    const dialog = page.getByRole("dialog", { name: "Menú de navegación" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Cerrar menú de navegación" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("la ruta inexistente ofrece una recuperación accesible", async ({ page }) => {
    const response = await page.goto("/ruta-inexistente-gerarai");
    expect(response?.status()).toBe(404);
    await expect(page.getByRole("heading", { name: "Página no encontrada", level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: "Volver al inicio" })).toHaveAttribute("href", "/");
    await expect(page.locator('#content a[href="/inicio"], #content a[href="/discover"], #content a[href="/watchlist"]')).toHaveCount(0);
  });
});
