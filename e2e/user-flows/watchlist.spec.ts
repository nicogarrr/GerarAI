import { backendCall, expect, expectHealthyPage, runUiE2E, test, VIEWPORTS, visit } from "./support";
import type { Page } from "@playwright/test";

// Un ticker US, uno de Londres (cotiza en peniques, GBp) y uno de París.
const SYMBOLS = ["AAPL", "VOD.L", "MC.PA"] as const;

async function resetWatchlist() {
  const { json } = await backendCall("GET", "/api/watchlist");
  const items = Array.isArray(json) ? (json as Array<{ symbol: string }>) : [];
  for (const item of items) {
    await backendCall("DELETE", `/api/watchlist/${encodeURIComponent(item.symbol)}`);
  }
}

function rowsFor(page: Page) {
  const mobile = (page.viewportSize()?.width ?? 1280) < 768;
  // En móvil la página tiene otros <article> legítimos (p. ej. «Valoración y
  // salud financiera»): solo cuentan las filas de membresía, las que llevan
  // el botón «Quitar … de la watchlist».
  return mobile
    ? page.locator("main article").filter({ has: page.locator("button[aria-label^='Quitar '][aria-label$=' de la watchlist']") })
    : page.locator("main table tbody tr");
}

async function addBySymbol(page: Page, symbol: string) {
  await page.getByRole("button", { name: "Añadir empresa" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Añadir a la watchlist" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("combobox", { name: "Buscar acciones para añadir a la watchlist" }).fill(symbol);
  // Este caso prueba alta manual: salir del buscador cancela su debounce
  // y cierra sugerencias antes de pulsar el botón del símbolo escrito.
  await dialog.getByRole("heading", { name: "Añadir a la watchlist" }).click();
  await dialog.getByRole("button", { name: `Añadir «${symbol}» por su símbolo` }).click();
  await expect(page.getByText(`${symbol} añadido a la watchlist`)).toBeVisible({ timeout: 20_000 });
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  // Success toast precedes router.refresh. The first add replaces the empty
  // state (and its dialog owner) with the table; wait for that server result
  // before opening a dialog that would otherwise be unmounted by the refresh.
  await expect(rowsFor(page).filter({ has: page.locator(`a[href="/research/${symbol}"]`) })).toHaveCount(1, { timeout: 30_000 });
}

for (const vp of VIEWPORTS) {
  test.describe(`watchlist (${vp.name})`, () => {
    test.skip(!runUiE2E, "Set E2E_UI_RUN=1 E2E_USER_FLOWS=1 to run the user-flow suite.");
    test.use(vp.use);
    test.describe.configure({ mode: "serial" });

    test("vacía → añadir US/.L/.PA → ordenar → quitar, incluida una fila ya quitada", async ({ page }) => {
      await resetWatchlist();
      await visit(page, "/watchlist");
      await expect(page.getByRole("heading", { name: "Watchlist", level: 1 })).toBeVisible();
      await expect(page.getByText("Tu Watchlist está vacía")).toBeVisible();
      await expectHealthyPage(page, "watchlist vacía");

      for (const symbol of SYMBOLS) await addBySymbol(page, symbol);
      await page.reload();
      await page.waitForLoadState("networkidle").catch(() => undefined);
      const rows = rowsFor(page);
      await expect(rows).toHaveCount(SYMBOLS.length, { timeout: 30_000 });
      for (const symbol of SYMBOLS) {
        await expect(page.locator("main").getByRole("link", { name: new RegExp(`^${symbol.replace(".", "\\.")}\\b`) }).first()).toBeVisible();
      }
      await expectHealthyPage(page, "watchlist con 3 valores");

      // ×100: Vodafone cotiza ~1 £ (≈100 peniques). Un importe en GBP/£ por
      // encima de 50 es la cifra en peniques rotulada como libras.
      const vodText = await rows.filter({ has: page.locator("a[href='/research/VOD.L']") }).first().innerText();
      for (const m of vodText.matchAll(/(\d{1,3}(?:\.\d{3})*,\d{2})\s*(?:GBP|£)/g)) {
        expect(Number(m[1].replace(/\./g, "").replace(",", ".")), `VOD.L en libras: ${vodText}`).toBeLessThan(50);
      }

      // Orden por símbolo A→Z y Z→A (enlace en la cabecera o en el menú móvil).
      await visit(page, "/watchlist?sort=symbol&dir=asc");
      const firstLinks = async () =>
        (await rows.evaluateAll((els) =>
          els.map((el) => (el.querySelector("a[href^='/research/']")?.getAttribute("href") ?? "").replace("/research/", "")),
        )).map(decodeURIComponent);
      expect(await firstLinks()).toEqual(["AAPL", "MC.PA", "VOD.L"]);
      await visit(page, "/watchlist?sort=symbol&dir=desc");
      expect(await firstLinks()).toEqual(["VOD.L", "MC.PA", "AAPL"]);
      await expectHealthyPage(page, "watchlist ordenada");

      // Una segunda pestaña se queda con la lista vieja.
      const stale = await page.context().newPage();
      await visit(stale, "/watchlist?sort=symbol&dir=desc");

      // Quitar VOD.L en la primera pestaña.
      const mobile = (page.viewportSize()?.width ?? 1280) < 768;
      const vodRow = rows.filter({ has: page.locator("a[href='/research/VOD.L']") }).first();
      if (!mobile) await vodRow.locator("summary").click().catch(() => undefined);
      await vodRow.getByRole("button", { name: "Quitar VOD.L de la watchlist" }).click();
      await expect(page.getByText("VOD.L eliminado de la watchlist")).toBeVisible({ timeout: 20_000 });
      await expect(rows).toHaveCount(2, { timeout: 20_000 });

      // Quitarlo otra vez desde la pestaña vieja: ya no está, así que el
      // resultado tiene que ser "fuera de la watchlist", no un error.
      const staleRows = rowsFor(stale);
      const staleVod = staleRows.filter({ has: stale.locator("a[href='/research/VOD.L']") }).first();
      if (!mobile) await staleVod.locator("summary").click().catch(() => undefined);
      await staleVod.getByRole("button", { name: "Quitar VOD.L de la watchlist" }).click();
      await expect(stale.getByText("VOD.L eliminado de la watchlist")).toBeVisible({ timeout: 20_000 });
      await expect(stale.getByText(/No se pudo eliminar/)).toHaveCount(0);
      await expect(staleRows).toHaveCount(2, { timeout: 20_000 });
      await stale.close();

      await expectHealthyPage(page, "tras quitar");
    });
  });
}
