import { backendCall, expect, expectHealthyPage, runUiE2E, test, VIEWPORTS, visit } from "./support";

// Operación en EUR (sin tipo de cambio): 100 a 30 € y venta de 40 a 40 €
// en 2025 → ganancia 400 € (transmisión 1.600, adquisición 1.200).
const CSV_TAX = [
  "symbol,action,quantity,price,date,fees,currency",
  "ITXE2E,BUY,100,30.00,2025-02-03,0,EUR",
  "ITXE2E,SELL,40,40.00,2025-09-15,0,EUR",
].join("\n");

async function resetPortfolio() {
  const { json } = await backendCall("GET", "/api/portfolio/transactions");
  const rows = Array.isArray(json) ? (json as Array<{ id: number }>) : [];
  for (const row of [...rows].sort((a, b) => b.id - a.id)) {
    await backendCall("DELETE", `/api/portfolio/transactions/${row.id}`);
  }
}

for (const vp of VIEWPORTS) {
  test.describe(`impuestos (${vp.name})`, () => {
    test.skip(!runUiE2E, "Set E2E_UI_RUN=1 E2E_USER_FLOWS=1 to run the user-flow suite.");
    test.use(vp.use);
    test.describe.configure({ mode: "serial" });

    test("IRPF 2025 (Modelo 100 y casillas por venta) y Modelo 720", async ({ page }) => {
      await resetPortfolio();
      const imported = await backendCall("POST", "/api/portfolio/import/ibkr/csv", { csv: CSV_TAX });
      expect(imported.status).toBe(200);

      await visit(page, "/taxes");
      await expect(page.getByRole("heading", { name: "Impuestos", level: 1 })).toBeVisible();
      await expectHealthyPage(page, "impuestos (ejercicio actual)");

      await page.getByRole("combobox", { name: "Ejercicio" }).selectOption("2025");
      await expect(page.getByRole("heading", { name: "Informe fiscal 2025" })).toBeVisible({ timeout: 30_000 });
      const main = page.locator("main");
      await expect(main.getByText("Plusvalías/minusvalías realizadas")).toBeVisible();

      // Modelo 100: importes exactos (ni ×100 ni ÷100).
      await expect(main.getByText(/0328 · Transmisión global\s*1\.600,00\s*€/)).toBeVisible();
      await expect(main.getByText(/0331 · Adquisición global\s*1\.200,00\s*€/)).toBeVisible();
      await expect(main.getByText(/0339 · Suma de ganancias\s*400,00\s*€/)).toBeVisible();
      // Escritorio: tablas; móvil: tarjetas (listas de definición).
      const rowRole = (page.viewportSize()?.width ?? 1280) < 768 ? "listitem" : "row";
      const sale = main.getByRole(rowRole).filter({ hasText: "ITXE2E" }).filter({ hasText: "15 sept 2025" });
      await expect(sale).toHaveCount(1);
      await expect(sale).toContainText("1.600,00 €");
      await expect(sale).toContainText("1.200,00 €");
      await expect(sale).toContainText("400,00 €");

      // Deducción por doble imposición: un TME no numérico no rompe la vista.
      const tme = page.getByRole("textbox", { name: "TME de la base liquidable del ahorro (%)" });
      await tme.fill("abc");
      await page.getByRole("button", { name: "Calcular vista previa" }).click();
      await expectHealthyPage(page, "TME inválido");
      await tme.fill("19,00");
      await page.getByRole("button", { name: "Calcular vista previa" }).click();
      await expectHealthyPage(page, "TME 19,00");

      // Modelo 720: tres categorías, cada una con su lectura y copy honesto.
      await expect(page.getByRole("heading", { name: "Modelo 720 (bienes en el extranjero)" })).toBeVisible();
      await expect(main.getByText("Valores en el extranjero")).toBeVisible();
      await expect(main.getByText("Cuentas en el extranjero")).toBeVisible();
      await expect(main.getByText("Inmuebles en el extranjero")).toBeVisible();
      await expect(main.getByText(/No concluyente|Obligado|No obligado|No evaluable/).first()).toBeVisible();
      await expect(page.getByRole("link", { name: "Completar datos fiscales" })).toHaveAttribute("href", "/settings");

      // Posiciones fiscales: 60 ITXE2E con base 1.800 €.
      const pos = main.getByRole(rowRole).filter({ hasText: "ITXE2E" }).filter({ hasText: "1.800,00 €" });
      await expect(pos).toHaveCount(1);
      await expect(pos).toContainText("60");
      await expect(pos).toContainText("1.800,00 €");
      await expectHealthyPage(page, "impuestos 2025");
    });
  });
}
