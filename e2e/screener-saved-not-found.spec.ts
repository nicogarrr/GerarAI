import { expect, test } from "@playwright/test";

const runUiE2E = process.env.E2E_UI_RUN === "1";

/**
 * /screeners/[screenId] con un id inválido o de un filtro que no existe debe
 * responder con la página 404 («Página no encontrada»), no con la página
 * genérica de error y su botón «Reintentar» (que nunca lo arregla).
 */
test.describe("filtro guardado inexistente", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  for (const screenId of ["abc", "0", "-3", "1.5", "999999"]) {
    test(`/screeners/${screenId} muestra la página no encontrada`, async ({ page }) => {
      // Con loading.tsx el segmento hace streaming y el código HTTP puede
      // salir 200 antes del notFound(): se comprueba lo que ve el usuario.
      await page.goto(`/screeners/${screenId}`);
      await expect(page.getByRole("heading", { name: "Página no encontrada", level: 1 })).toBeVisible();
      await expect(page.getByText("No se pudo completar la operación")).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Reintentar" })).toHaveCount(0);
    });
  }
});
