import { execFileSync } from "node:child_process";
import path from "node:path";

import { backendCall, expect, expectHealthyPage, runUiE2E, test, VIEWPORTS, visit } from "./support";

/**
 * Funciones nuevas desde el 28-10-2026: posición real en la ficha, operaciones
 * simuladas ancladas a la tesis junto al diario (con etiquetas de versión),
 * lectura editorial de la tesis + impresión, avisos DCA en Ajustes, histórico
 * DCA plegado en la watchlist y la navegación única de la ficha. Mismas
 * comprobaciones por página que el resto de la suite (support.ts).
 *
 * Estado sembrado por la API firmada (como e2e-browser-user) y, para la
 * tesis (no hay API sin LLM), por e2e/user-flows/seed_thesis.py contra la
 * misma base SQLite del backend E2E.
 */

const TICKER = "MSFT"; // ficha determinista del fixture E2E

async function seedHoldingAndPaper() {
  const positions = await backendCall("GET", "/api/portfolio/positions");
  const held = Array.isArray(positions.json)
    && (positions.json as Array<{ ticker: string }>).some((p) => p.ticker === TICKER);
  if (!held) {
    const buy = await backendCall("POST", "/api/portfolio/transactions", {
      ticker: TICKER, action: "buy", quantity: 10, price: 400, trade_date: "2025-01-10", currency: "USD",
    });
    expect(buy.status, JSON.stringify(buy.json)).toBe(201);
  }
  const paper = await backendCall("POST", "/api/paper-trading/proposals", {
    proposal_key: "e2e-user-flows-msft", ticker: TICKER, direction: "long", horizon: "short",
    thesis: "Tesis simulada E2E para MSFT: Azure sostiene el crecimiento.", conviction: 0.6,
    proposed_entry: 390, stop: 350, target: 450, quantity: 5,
    inference_basis: "Base de inferencia E2E determinista", currency: "USD",
  });
  // 409 = ya sembrada en una pasada anterior (clave idempotente).
  expect([201, 409], JSON.stringify(paper.json)).toContain(paper.status);
  const journal = await backendCall("GET", `/api/companies/${TICKER}/decision-journal`);
  if (!Array.isArray(journal.json) || journal.json.length === 0) {
    const entry = await backendCall("POST", `/api/companies/${TICKER}/decision-journal`, {
      decision: "buy", rationale: "Compra E2E: Azure por encima del 20 %", what_must_be_true: ["Azure crece >20 %"],
    });
    expect(entry.status, JSON.stringify(entry.json)).toBe(201);
  }
}

function seedThesis() {
  const cwd = path.resolve(process.cwd(), "data-engine");
  execFileSync(process.env.PYTHON_BIN ?? "python", ["../e2e/user-flows/seed_thesis.py", TICKER], {
    cwd,
    env: {
      ...process.env,
      APP_ENV: "test",
      PYTHONPATH: ".",
      DATABASE_URL: process.env.E2E_UI_DATABASE_URL ?? "sqlite:///./cavaai_ui_e2e.db",
    },
    stdio: "pipe",
    timeout: 60_000,
  });
}

for (const vp of VIEWPORTS) {
  test.describe(`funciones nuevas (${vp.name})`, () => {
    test.skip(!runUiE2E, "Set E2E_UI_RUN=1 E2E_USER_FLOWS=1 to run the user-flow suite.");
    test.use(vp.use);
    test.describe.configure({ mode: "serial" });

    test("ficha: «Tu posición» con cifras reales y navegación de una sola capa", async ({ page }) => {
      await seedHoldingAndPaper();
      await visit(page, `/research/${TICKER}`);
      const heading = page.getByRole("heading", { name: "Tu posición" });
      await expect(heading).toBeVisible();
      // El panel = el ancestro más cercano del título que contiene la lista de cifras.
      const panel = heading.locator("xpath=ancestor::*[.//dl][1]");
      await expect(panel.getByText("Acciones", { exact: true })).toBeVisible();
      // 10 acciones a 400 $: coste medio en la divisa del valor, nunca ×100 ni ceros inventados.
      await expect(panel.getByText(/^\$400[.,]00$|^400,00\s?(US)?\$$/)).toBeVisible();
      await expect(panel.getByText(/40[.,]?000/)).toHaveCount(0);
      await expect(panel.getByRole("link", { name: "Ver en la cartera" })).toHaveAttribute("href", "/portfolio");
      // Sin FX en la base E2E: la ficha lo dice en vez de pintar 0 €.
      await expect(panel.getByText(/Sin valor en EUR|Sin coste en EUR/).first()).toBeVisible();

      // Una sola capa de navegación de empresa (c959c94) y sin desborde.
      await expect(page.getByRole("navigation", { name: "Secciones de la empresa" })).toHaveCount(1);
      await expectHealthyPage(page, "ficha con posición");
    });

    test("Seguir: diario con versiones legibles y operaciones simuladas de la empresa", async ({ page }) => {
      await seedHoldingAndPaper();
      await visit(page, `/research/${TICKER}?view=changes#diario-decisiones`);
      await expect(page.locator("#diario-decisiones")).toBeVisible({ timeout: 30_000 });
      // 23fb53d: el diario nombra versiones, nunca claves internas (thesis_version_id).
      const label = page.getByText(/^Contra (tesis|sin tesis)/).first();
      await expect(label).toBeVisible();
      await expect(label).toHaveText(/^Contra (tesis v\d+|tesis registrada|sin tesis) · (modelo v\d+|modelo registrado|sin modelo)$/);
      await expect(page.locator("main")).not.toContainText(/thesis_version_id|model_version_id/);

      const paper = page.locator("#paper-trading");
      await expect(paper.getByRole("heading", { name: "Operaciones simuladas de esta empresa" })).toBeVisible();
      const list = paper.getByRole("list", { name: `Operaciones simuladas de ${TICKER}` });
      await expect(list.getByRole("listitem").first()).toBeVisible();
      await expect(list.getByText("Largo · operación a 30 días").first()).toBeVisible();
      await expect(list.getByText(/Pendiente de entrada|Abierta|Cerrada/).first()).toBeVisible();
      // ed0ab9a: cada propuesta dice a qué tesis se ancló (o que no había).
      await expect(list.getByText(/tesis/i).first()).toBeVisible();
      await expect(paper.getByRole("link", { name: /Ver el detalle/ })).toHaveAttribute("href", "/propicks?tab=paper");
      await expectHealthyPage(page, "Seguir con diario y paper");
    });

    test("tesis: lectura editorial e impresión sin chrome de la app", async ({ page }) => {
      await visit(page, `/research/${TICKER}`); // garantiza la empresa en la base antes de sembrar
      seedThesis();
      await visit(page, `/research/${TICKER}/tesis`);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expectHealthyPage(page, "tesis");
      const main = page.locator("main");
      // Tesis publicada con modelo publicable: lectura editorial completa, no
      // el texto archivado ni el estado «sin tesis» ni un error de servicio.
      await expect(main).not.toContainText(/Aún no hay ninguna tesis publicada|Texto archivado|no respondió|reintenta/i);
      await expect(main.getByText("Tesis de inversión", { exact: true })).toBeVisible();
      await expect(main.getByText("v2", { exact: true }).first()).toBeVisible();
      for (const title of ["Resumen ejecutivo", "Escenarios y valoración", "Catalizadores", "Riesgos"]) {
        await expect(main.getByRole("heading", { name: title }).first()).toBeVisible();
      }
      await expect(main.getByText(/Azure mantiene crecimientos superiores al 20/).first()).toBeVisible();
      // Escenarios en dólares tal cual (sin ×100): 280 / 420 / 520 por acción.
      for (const value of ["$280.00", "$420.00", "$520.00"]) {
        await expect(main.getByText(value, { exact: true }).first()).toBeVisible();
      }

      await page.emulateMedia({ media: "print" });
      await expect(main.getByText("Tesis de inversión", { exact: true })).toBeVisible();
      await expect(page.getByRole("link", { name: "PDF" })).toBeHidden();
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.getByRole("button", { name: "Abrir el cerebro" })).toBeHidden();
      await expect(page.getByRole("navigation", { name: "Ruta de navegación" })).toBeHidden();
      expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe("rgb(255, 255, 255)");
      await expectHealthyPage(page, "tesis impresa");
    });

    test("Ajustes → Avisos DCA y watchlist con histórico DCA plegado", async ({ page }) => {
      await visit(page, "/settings#dca");
      const dca = page.locator("#dca");
      await expect(dca.getByRole("heading", { name: "Avisos DCA" })).toBeVisible({ timeout: 30_000 });
      await expect(dca.getByText(/Al subir, avisar desde/)).toBeVisible();
      await expect(dca.getByText(/Al bajar, avisar hasta/)).toBeVisible();
      await expectHealthyPage(page, "ajustes DCA");

      await visit(page, "/watchlist");
      await expect(page.getByRole("heading", { name: "Watchlist", level: 1 })).toBeVisible();
      // eb98e1e: el histórico por empresa va plegado; nunca veredictos duplicados.
      const history = page.getByRole("list", { name: "Histórico DCA por empresa" });
      if (await history.count()) {
        const items = await history.getByRole("listitem").allInnerTexts();
        expect(new Set(items).size, "veredictos DCA duplicados").toBe(items.length);
      }
      await expectHealthyPage(page, "watchlist con DCA");
    });
  });
}
