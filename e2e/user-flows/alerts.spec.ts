import { expect, expectHealthyPage, runUiE2E, test, VIEWPORTS, visit } from "./support";
import type { Page } from "@playwright/test";

async function deleteAllAlerts(page: Page) {
  for (let i = 0; i < 20; i += 1) {
    const del = page.getByRole("button", { name: /^Eliminar alerta:/ }).first();
    if (!(await del.isVisible().catch(() => false))) return;
    const before = await page.getByRole("button", { name: /^Eliminar alerta:/ }).count();
    await del.click();
    const confirm = page.getByRole("alertdialog").or(page.getByRole("dialog")).filter({ hasText: "Eliminar alerta" });
    await expect(confirm).toBeVisible();
    await confirm.getByRole("button", { name: "Eliminar", exact: true }).click();
    await expect(page.getByRole("button", { name: /^Eliminar alerta:/ })).toHaveCount(before - 1, { timeout: 20_000 });
  }
}

async function openCreate(page: Page) {
  await page.getByRole("button", { name: /Nueva Alerta|Crear la primera alerta/ }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  return dialog;
}

for (const vp of VIEWPORTS) {
  test.describe(`alertas (${vp.name})`, () => {
    test.skip(!runUiE2E, "Set E2E_UI_RUN=1 E2E_USER_FLOWS=1 to run the user-flow suite.");
    test.use(vp.use);
    test.describe.configure({ mode: "serial" });

    test("validación de símbolo y valor, alta con coma decimal y baja", async ({ page }) => {
      await visit(page, "/alerts");
      await expect(page.getByRole("heading", { name: "Alertas", level: 1 })).toBeVisible();
      await deleteAllAlerts(page);
      await expect(page.getByText("No tienes alertas configuradas")).toBeVisible();
      await expect(page.getByText(/Crea tu primera alerta/)).toBeVisible();
      await expectHealthyPage(page, "alertas vacías");

      const dialog = await openCreate(page);
      const symbol = dialog.getByRole("combobox", { name: "Símbolo" }).or(dialog.getByLabel("Símbolo")).first();
      const value = dialog.locator("#value");
      const create = dialog.getByRole("button", { name: /^Crear/ });

      // Símbolo inválido: aviso en español, sin 500 ni alta.
      await symbol.fill("$$$ <script>");
      await value.fill("100");
      await create.click();
      await expect(page.getByText(/Introduce un símbolo válido/)).toBeVisible();
      await expect(dialog).toBeVisible();

      // Formato válido pero símbolo inexistente: lo rechaza el backend y el
      // usuario lee el motivo (antes: POST /alerts 500 y «motor caído»).
      await symbol.fill("ZZZQX");
      await dialog.getByRole("heading").first().click();
      await create.click();
      await expect(page.getByText(/Símbolo no reconocido: ZZZQX/).first()).toBeVisible({ timeout: 20_000 });
      await expect(page.getByText(/motor de análisis no responde/)).toHaveCount(0);
      await expect(dialog).toBeVisible();

      // Valor no numérico. MSFT es la empresa sembrada del entorno de test.
      await symbol.fill("MSFT");
      // Cierra las sugerencias del buscador sin cerrar el diálogo.
      await dialog.getByRole("heading").first().click();
      await value.fill("abc");
      await create.click();
      await expect(page.getByText(/Introduce un valor numérico válido/)).toBeVisible();

      // Alta con coma decimal es-ES: 250,50 se guarda como 250,5 (ni ×100).
      await value.fill("250,50");
      await create.click();
      await expect(page.getByText("Alerta creada").first()).toBeVisible({ timeout: 20_000 });
      await expect(dialog).toBeHidden();
      await expect(page.getByRole("button", { name: /^Eliminar alerta: MSFT: Precio por encima de 250,5$/ })).toBeVisible();
      const row = page.locator("main").getByText(/MSFT/).first();
      await expect(row).toBeVisible();
      await expect(page.locator("main")).toContainText(/250,5/);
      await expect(page.locator("main")).not.toContainText(/25\.050|25050/);
      await expectHealthyPage(page, "con una alerta");

      await deleteAllAlerts(page);
      await expect(page.getByText("No tienes alertas configuradas")).toBeVisible();
      await expectHealthyPage(page, "tras borrar");
    });
  });
}
