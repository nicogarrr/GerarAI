import { expect, test } from "@playwright/test";

const runUiE2E = process.env.E2E_UI_RUN === "1";

/**
 * Cierre de hallazgos legales/UX visibles. Gated como el resto de e2e UI.
 * Los guards estáticos equivalentes viven en
 * scripts/frontend-audit-closure-guard.test.ts.
 */
test.describe("frontend audit closure", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test("las páginas legales publicadas llevan disclaimer y noindex", async ({ page }) => {
    for (const path of ["/privacidad", "/terminos"]) {
      await page.goto(path);
      // Documentos ya aprobados y completos: el aviso de borrador se sustituyó
      // por el disclaimer (ver 3630e76 y el guard equivalente de scripts/).
      await expect(page.getByText(/informativo y no constituye asesoramiento jurídico/).first()).toBeVisible();
      const robots = await page.locator('meta[name="robots"]').getAttribute("content");
      expect(robots ?? "").toContain("noindex");
    }
    const sitemap = await page.request.get("/sitemap.xml");
    expect(sitemap.ok()).toBeTruthy();
    const xml = await sitemap.text();
    expect(xml).not.toContain("/privacidad");
    expect(xml).not.toContain("/terminos");
  });

  test("el alta muestra consentimiento enlazado a Términos y Privacidad", async ({ page }) => {
    await page.goto("/sign-up");
    const checkbox = page.getByRole("checkbox", { name: /Términos de uso y la Política de privacidad/i }).first();
    await expect(checkbox).toBeVisible();
    await expect(checkbox).not.toBeChecked();
    await expect(page.getByRole("link", { name: "Términos de uso" }).first()).toHaveAttribute("href", "/terminos");
    await expect(page.getByRole("link", { name: "Política de privacidad" }).first()).toHaveAttribute("href", "/privacidad");
  });

  test("el 404 ofrece solo recuperación pública", async ({ page }) => {
    const response = await page.goto("/ruta-inexistente-cavaai");
    expect(response?.status()).toBe(404);
    await expect(page.getByRole("heading", { name: "Página no encontrada", level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: "Volver al inicio" })).toHaveAttribute("href", "/");
    await expect(page.getByRole("link", { name: "Ver la metodología" })).toHaveAttribute("href", "/metodologia");
    await expect(page.getByRole("link", { name: "Centro de ayuda" })).toHaveAttribute("href", "/help");
    // Con E2E_AUTH_BYPASS el 404 se renderiza con el shell autenticado (sidebar con
    // /inicio, /discover, /watchlist por diseno, ver canonical-404-shell.test.ts).
    // La garantia es sobre el contenido del 404, no sobre el shell.
    await expect(page.locator('#content a[href="/inicio"], #content a[href="/discover"], #content a[href="/watchlist"]')).toHaveCount(0);
  });

  test("sin SMTP, recuperación de contraseña no promete un envío", async ({ page }) => {
    await page.goto("/forgot-password");
    await expect(page.getByText(/no podemos\s+enviarte ningún enlace/i)).toBeVisible();
    await expect(page.getByText("El restablecimiento por correo no está disponible.")).toBeVisible();
    await expect(page.getByLabel("Email de la cuenta")).toHaveCount(0);
  });
});
