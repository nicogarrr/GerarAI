import { backendCall, expect, expectHealthyPage, runUiE2E, test, VIEWPORTS, visit } from "./support";
import type { Page } from "@playwright/test";

const CSV_EN = [
  "symbol,action,quantity,price,date,fees,currency",
  "AAPL,BUY,10,150.00,2025-03-10,1.00,USD",
  "KO,BUY,20,58.00,2024-06-01,1.00,USD",
].join("\n");

// Excel/LibreOffice en español: «;» como separador y coma decimal.
const CSV_ES = [
  "symbol;action;quantity;price;date;fees;currency",
  "MSFT;BUY;5;350,50;2025-02-03;1,25;USD",
].join("\n");

async function resetPortfolio() {
  for (let page = 0; page < 5; page += 1) {
    const { json } = await backendCall("GET", "/api/portfolio/transactions");
    const rows = Array.isArray(json) ? (json as Array<{ id: number }>) : [];
    if (rows.length === 0) return;
    // Ventas primero no aplica: se borran de la más nueva a la más vieja.
    for (const row of [...rows].sort((a, b) => b.id - a.id)) {
      await backendCall("DELETE", `/api/portfolio/transactions/${row.id}`);
    }
  }
}

async function upload(page: Page, name: string, content: string) {
  await page.getByRole("tab", { name: "Posiciones" }).click();
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Subir fichero" }).first().click();
  await (await chooser).setFiles({ name, mimeType: "text/csv", buffer: Buffer.from(content, "utf8") });
}

for (const vp of VIEWPORTS) {
  test.describe(`cartera (${vp.name})`, () => {
    test.skip(!runUiE2E, "Set E2E_UI_RUN=1 E2E_USER_FLOWS=1 to run the user-flow suite.");
    test.use(vp.use);
    test.describe.configure({ mode: "serial" });

    test("IBKR CSV (en-US y es-ES con «;») → posiciones → distribución → tearsheet", async ({ page }) => {
      await resetPortfolio();
      await visit(page, "/portfolio");
      await expect(page.getByRole("heading", { name: "Resumen", level: 1 })).toBeVisible();
      // El servidor de Next cachea las lecturas de cartera unos segundos; el
      // reset va directo al backend, así que se pide una lectura fresca.
      const empty = page.getByText(/Aún no tienes posiciones/).first();
      if (!(await empty.isVisible().catch(() => false))) {
        await page.getByRole("button", { name: "Actualizar lecturas" }).click();
      }
      await expect(empty).toBeVisible({ timeout: 30_000 });
      await expectHealthyPage(page, "cartera vacía");

      await upload(page, "ibkr-en.csv", CSV_EN);
      await expect(page.getByText("IBKR CSV: 2 operaciones importadas")).toBeVisible({ timeout: 30_000 });

      await upload(page, "ibkr-es.csv", CSV_ES);
      await expect(page.getByText("IBKR CSV: 1 operación importada")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByText(/Importación falló|cabecera del CSV/)).toHaveCount(0);

      // El backend tiene las tres operaciones con los importes exactos.
      const { json } = await backendCall("GET", "/api/portfolio/transactions");
      const txs = (json as Array<{ ticker: string; quantity: string | number; price: string | number; fees: string | number }>)
        .map((t) => [t.ticker, Number(t.quantity), Number(t.price), Number(t.fees)])
        .sort();
      expect(txs).toEqual([
        ["AAPL", 10, 150, 1],
        ["KO", 20, 58, 1],
        ["MSFT", 5, 350.5, 1.25],
      ]);

      await page.reload();
      await page.waitForLoadState("networkidle").catch(() => undefined);
      await page.getByRole("tab", { name: "Posiciones" }).click();
      for (const ticker of ["AAPL", "KO", "MSFT"]) {
        await expect(page.getByRole("tabpanel", { name: "Posiciones" }).getByRole("link", { name: ticker, exact: true }).first()).toBeVisible();
      }
      await expectHealthyPage(page, "posiciones");

      await page.getByRole("tab", { name: "Resumen" }).click();
      const panel = page.getByRole("tabpanel", { name: "Resumen" });
      await expect(panel.getByText("Añade posiciones para ver la distribución")).toHaveCount(0);
      // Con precio y tipo de cambio, el reparto enlaza cada posición; sin
      // ellos (CI sin red) tiene que decirlo, nunca quedarse en blanco.
      await expect(
        panel.getByRole("link", { name: "MSFT", exact: true })
          .or(panel.getByText(/Distribución incompleta|Distribución N\/D/))
          .first(),
      ).toBeVisible();
      await expect(panel.getByText("Estadísticas de rentabilidad").first()).toBeVisible();
      await expectHealthyPage(page, "resumen con posiciones");

      for (const tab of ["Previsión", "Dividendos", "Movimientos", "Factores"]) {
        await page.getByRole("tab", { name: tab }).click();
        await expect(page.getByRole("tabpanel", { name: tab })).toBeVisible();
        await expectHealthyPage(page, `pestaña ${tab}`);
      }
    });
  });
}
