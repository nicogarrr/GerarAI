import { expect, test } from "@playwright/test";

const runUiE2E = process.env.E2E_UI_RUN === "1";

test.describe("public authentication shell", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test("renders GerarAI sign-in, validates required fields and links to sign-up", async ({ page }) => {
    await page.goto("/sign-in");

    await expect(page).toHaveTitle(/GerarAI/);
    await expect(page.getByRole("heading", { name: "Bienvenido de nuevo" })).toBeVisible();
    await expect(page.getByLabel("Email")).toBeVisible();
    await expect(page.getByLabel("Contraseña", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Iniciar sesión" }).click();
    await expect(page.getByText("El email es obligatorio")).toBeVisible();
    await expect(page.getByText("La contraseña es obligatoria")).toBeVisible();

    await page.screenshot({ path: "test-results/gerarai-sign-in-validation.png", fullPage: true });
    await page.getByRole("link", { name: "Crear cuenta" }).click();
    await expect(page).toHaveURL(/\/sign-up$/);
    await expect(page.getByRole("heading", { name: "Crea tu cuenta" })).toBeVisible();
  });

  test("sign-up keeps Radix selects out of native validation and preloads canonical defaults", async ({ page }) => {
    await page.goto("/sign-up");

    const form = page.locator("form");
    await expect(form).toBeVisible();
    // Radix renderiza un <select> oculto sin opciones; si lleva `required`, el
    // navegador aborta el submit antes de react-hook-form. La obligatoriedad
    // vive en las reglas del formulario, no en el control nativo.
    expect(await form.locator("select[required]").count()).toBe(0);

    // Los defaults deben ser valores canonicos de las opciones (no etiquetas
    // en mayusculas que dejan el Select en blanco y envian un payload invalido).
    await expect(form.getByRole("combobox").nth(1)).toHaveText(/Crecimiento a largo plazo/);
    await expect(form.getByRole("combobox").nth(2)).toHaveText(/Moderado/);
    await expect(form.getByRole("combobox").nth(3)).toHaveText(/Tecnolog/);
    await expect(form.getByRole("button", { name: "Crear cuenta", exact: true })).toBeEnabled();
  });
});


test.describe("mobile authentication layout", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("sign-in form is fully reachable at 390px without inner scroll traps", async ({ page }) => {
    await page.goto("/sign-in");

    // Regresión: .auth-layout usaba h-screen + overflow-hidden en móvil, lo que
    // comprimía el formulario en una tira de ~190px con scroll interno oculto
    // y dejaba el botón fuera del viewport.
    await expect(page.getByRole("heading", { name: "Bienvenido de nuevo" })).toBeInViewport();
    await expect(page.getByLabel("Email")).toBeInViewport();
    await expect(page.getByLabel("Contraseña", { exact: true })).toBeInViewport();
    await expect(page.getByRole("button", { name: "Iniciar sesión" })).toBeInViewport();

    // La página completa hace scroll normal en documento (no hay trampas internas):
    // ni el documento está clavado con overflow-hidden (la regresión original) ni
    // el botón vive dentro de un contenedor con scroll o recorte propio. Si el
    // contenido crece, hace scroll el documento. (El contenido ya no desborda
    // 844px, así que scrollHeight > innerHeight dejó de discriminar.)
    const traps = await page.evaluate(() => {
      const doc = getComputedStyle(document.documentElement).overflowY;
      const body = getComputedStyle(document.body).overflowY;
      const submit = [...document.querySelectorAll("button")].find(
        (el) => el.textContent?.trim() === "Iniciar sesión",
      );
      let innerTrap: string | null = null;
      for (let el = submit?.parentElement ?? null; el; el = el.parentElement) {
        const { overflowY } = getComputedStyle(el);
        if (
          (overflowY === "auto" || overflowY === "scroll" || overflowY === "hidden") &&
          el.scrollHeight > el.clientHeight
        ) {
          innerTrap = el.className || el.tagName;
          break;
        }
      }
      return { doc, body, innerTrap };
    });
    expect(traps.doc).not.toBe("hidden");
    expect(traps.body).not.toBe("hidden");
    expect(traps.innerTrap).toBeNull();
    await page.screenshot({ path: "test-results/gerarai-sign-in-mobile.png", fullPage: true });
  });
});

test.describe("company research workspace", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test("loads the compact snapshot and lazy-loads research modules", async ({ page }) => {
    await page.goto("/research/MSFT");

    await expect(page).toHaveURL(/\/research\/MSFT$/);
    await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
    const quote = page.getByTestId('company-header-quote');
    await expect(quote.getByText(/^336,56\sUS\$$/)).toBeVisible();
    await expect(quote.getByTestId('company-metric-strip')).toBeVisible();
    // Cabecera limpia (Nico, 30-oct-2026): sin línea de procedencia ni «Más detalle».
    await expect(quote.getByText('Fixture local · 17:00 (Madrid)', { exact: true })).toHaveCount(0);
    await expect(quote.getByText('Más detalle', { exact: true })).toHaveCount(0);
    await expect(quote.getByText(/Sesión regular del/)).toHaveCount(0);
    // Vista general compacta: la cabecera de tesis resume el estado; el
    // modelo vive en su modulo (pestaña Números).
    await expect(page.getByRole("heading", { name: "Última tesis" })).toBeVisible();

    // El modelo vive en el desplegable «Análisis avanzado» (IA nueva de la
    // ficha: Resumen / Finanzas / Fuentes + avanzado).
    await page.locator('summary', { hasText: "Análisis avanzado" }).click();
    await page.getByRole("navigation", { name: "Análisis avanzado" }).getByRole("link", { name: "Modelo a largo plazo", exact: true }).click();
    await expect(page).toHaveURL(/view=model/);
    await expect(page.getByRole("heading", { name: "Modelo fundamental a largo plazo" })).toBeVisible();

    // Con el modelo activo el desplegable avanzado ya queda abierto.
    await page.getByRole("navigation", { name: "Análisis avanzado" }).getByRole("link", { name: "Cambios y revisiones", exact: true }).click();
    await expect(page).toHaveURL(/view=changes/);
    await expect(page.getByRole("heading", { name: "Diario de decisiones" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Expectativa vs realidad" })).toBeVisible();
    await page.screenshot({ path: "test-results/gerarai-company-workspace.png", fullPage: true });
  });
});
