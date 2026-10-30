import { backendCall, expect, expectHealthyPage, runUiE2E, test, VIEWPORTS, visit } from "./support";
import type { Page } from "@playwright/test";

async function chooseCurrency(page: Page, code: string) {
  await page.getByRole("combobox", { name: "Divisa base" }).click();
  await page.getByRole("option", { name: new RegExp(`^${code}\\b`) }).click();
  await page.getByRole("button", { name: "Guardar", exact: true }).click();
  await expect(page.getByText(new RegExp(`Divisa base: ${code}\\. Cartera revalorada\\.`)).first()).toBeVisible({ timeout: 30_000 });
}

for (const vp of VIEWPORTS) {
  test.describe(`ajustes y divisa base (${vp.name})`, () => {
    test.skip(!runUiE2E, "Set E2E_UI_RUN=1 E2E_USER_FLOWS=1 to run the user-flow suite.");
    test.use(vp.use);
    test.describe.configure({ mode: "serial" });

    test("cambiar la divisa base a USD se refleja en la cartera y se restaura a EUR", async ({ page }) => {
      await visit(page, "/settings");
      await expect(page.getByRole("heading", { name: "Ajustes", level: 1 })).toBeVisible();
      for (const section of ["IBKR", "Divisa", "Telegram", "IA", "Fiscalidad"]) {
        await expect(page.getByRole("navigation", { name: "Secciones de ajustes" }).getByRole("link", { name: section })).toBeVisible();
      }
      await expect(page.getByRole("button", { name: "Conectar e importar" })).toBeDisabled();
      await expectHealthyPage(page, "ajustes");

      const combo = page.getByRole("combobox", { name: "Divisa base" });
      if (!/EUR/.test((await combo.textContent()) ?? "")) await chooseCurrency(page, "EUR");
      await expect(page.getByRole("button", { name: "Guardar", exact: true })).toBeDisabled();

      await chooseCurrency(page, "USD");
      const { json } = await backendCall("GET", "/api/portfolio/summary");
      expect((json as { base_currency?: string }).base_currency).toBe("USD");

      await page.reload();
      await expect(page.getByRole("combobox", { name: "Divisa base" })).toContainText("USD");
      await expectHealthyPage(page, "ajustes en USD");

      await visit(page, "/portfolio");
      await expect(page.getByRole("heading", { name: "Resumen", level: 1 })).toBeVisible();
      // Ningún total de cartera sigue en euros tras cambiar la divisa base.
      const summary = page.getByRole("tabpanel", { name: "Resumen" });
      await expect(summary).not.toContainText(/Valor total \(neto\)\s*[\d.,]+\s*€/);
      await expectHealthyPage(page, "cartera en USD");

      await visit(page, "/settings");
      await chooseCurrency(page, "EUR");
      await expectHealthyPage(page, "ajustes restaurados");
    });
  });
}
