import { backendTransactions, backendCall, expect, expectHealthyPage, runUiE2E, test, VIEWPORTS, visit } from "./support";

/**
 * Primer uso: desde «Primeros pasos» de Inicio, «Añadir» abre directamente el
 * alta en destino (sin un segundo clic), una compra se registra aunque el
 * buscador no devuelva sugerencias (CI y local van sin proveedor de búsqueda:
 * «Usar «KO» como símbolo»), se corrige y se borra desde Movimientos.
 */
const SYMBOL = "KO";

async function deleteTransactionsOf(symbol: string) {
  const json = await backendTransactions();
  const rows = json;
  for (const row of rows.filter((r) => r.ticker === symbol).sort((a, b) => b.id - a.id)) {
    await backendCall("DELETE", `/api/portfolio/transactions/${row.id}`);
  }
}

async function resetAll() {
  const json = await backendTransactions();
  const rows = json;
  for (const row of [...rows].sort((a, b) => b.id - a.id)) {
    await backendCall("DELETE", `/api/portfolio/transactions/${row.id}`);
  }
  const wl = await backendCall("GET", "/api/watchlist");
  for (const item of Array.isArray(wl.json) ? (wl.json as Array<{ symbol: string }>) : []) {
    await backendCall("DELETE", `/api/watchlist/${encodeURIComponent(item.symbol)}`);
  }
}

for (const vp of VIEWPORTS) {
  test.describe(`primer uso (${vp.name})`, () => {
    test.skip(!runUiE2E, "Set E2E_UI_RUN=1 E2E_USER_FLOWS=1 to run the user-flow suite.");
    test.use(vp.use);
    test.describe.configure({ mode: "serial" });

    test("Inicio → «Añadir» inversión abre el alta, registra una compra sin sugerencias, la edita y la borra", async ({ page }) => {
      await resetAll();
      await visit(page, "/inicio");
      // La lectura de cartera del servidor de Next se cachea 15 s: tras vaciar
      // la cartera por backend, Inicio pasa a «Primeros pasos» al caducar.
      const firstSteps = page.getByText("Primeros pasos");
      await expect(async () => {
        if (!(await firstSteps.isVisible())) await page.reload({ waitUntil: "domcontentloaded" });
        await expect(firstSteps).toBeVisible({ timeout: 10_000 });
      }).toPass({ timeout: 60_000, intervals: [2_000, 4_000] });
      // Sin fuente de noticias (CI y local) Inicio dice «no hay noticias», no
      // un aviso de error con un «Reintentar» que no arregla nada.
      await expect(page.getByRole("heading", { name: "Noticias destacadas" })).toBeVisible({ timeout: 30_000 });
      await expect(page.getByText("No se pudieron cargar las noticias")).toHaveCount(0);
      await expectHealthyPage(page, "inicio vacío");

      await page.getByRole("link", { name: /Añadir\s*inversión/ }).click();
      await expect(page).toHaveURL(/\/portfolio(?!.*anadir)/, { timeout: 30_000 });
      const dialog = page.getByRole("dialog", { name: "Nueva inversión" });
      await expect(dialog).toBeVisible({ timeout: 30_000 });

      await dialog.getByPlaceholder(/Buscar por nombre o símbolo/).fill(SYMBOL.toLowerCase());
      await dialog.getByRole("button", { name: `Usar «${SYMBOL}» como símbolo` }).click();
      await dialog.getByLabel("Cantidad").fill("12");
      await dialog.getByLabel(/^Precio/).fill("58,25");
      await dialog.getByLabel("Fecha").fill("2025-03-14");
      await dialog.getByRole("button", { name: /Registrar|Añadir|Guardar/ }).last().click();
      await expect(page.getByText("Transacción registrada")).toBeVisible({ timeout: 30_000 });
      await expect(dialog).toBeHidden();

      const json = await backendTransactions();
      const mine = (json as Array<{ ticker: string; quantity: string | number; price: string | number }>).filter((t) => t.ticker === SYMBOL);
      expect(mine.map((t) => [Number(t.quantity), Number(t.price)])).toEqual([[12, 58.25]]);
      await expectHealthyPage(page, "tras registrar la compra");

      // Se corrige desde Movimientos (editar) y el cambio llega al backend.
      await page.getByRole("tab", { name: "Movimientos" }).click();
      const movimientos = page.getByRole("tabpanel", { name: "Movimientos" });
      await movimientos.getByRole("button", { name: `Editar transacción de ${SYMBOL}` }).first().click();
      const edit = page.getByRole("dialog", { name: "Editar transacción" });
      await expect(edit).toBeVisible();
      await edit.getByLabel("Cantidad").fill("15");
      await edit.getByRole("button", { name: "Guardar cambios" }).click();
      await expect(page.getByText("Transacción actualizada")).toBeVisible({ timeout: 30_000 });
      await expect(edit).toBeHidden();
      const edited = await backendTransactions();
      expect((edited as Array<{ ticker: string; quantity: string | number }>).filter((t) => t.ticker === SYMBOL).map((t) => Number(t.quantity))).toEqual([15]);

      // Y se borra desde Movimientos (con confirmación), también por la UI: así
      // la caché de lecturas de cartera se invalida igual que en uso real.
      await page.getByRole("tab", { name: "Movimientos" }).click();
      const panel = page.getByRole("tabpanel", { name: "Movimientos" });
      await panel.getByRole("button", { name: "Eliminar transacción" }).first().click();
      const confirm = page.getByRole("alertdialog").or(page.getByRole("dialog", { name: "Eliminar transacción" })).first();
      await expect(confirm).toContainText(`15 ${SYMBOL}`);
      await confirm.getByRole("button", { name: "Eliminar" }).click();
      await expect(page.getByText("Transacción eliminada")).toBeVisible({ timeout: 30_000 });
      const after = await backendTransactions();
      expect((after as Array<{ ticker: string }>).filter((t) => t.ticker === SYMBOL)).toEqual([]);
      await expectHealthyPage(page, "tras borrar la compra");
    });

    test.afterAll(async () => {
      await deleteTransactionsOf(SYMBOL);
    });
  });
}
