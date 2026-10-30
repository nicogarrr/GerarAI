import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { E2E_UI_BACKEND_URL, E2E_PYTHON_BIN, e2eUiDatabasePath } from "./fixtures/e2e-env";

// Quick win UX 6: /research ordenado por relevancia. Semilla firmada
// (patrón f339, tenant del bypass de navegador): cuatro empresas E2E*,
// posición abierta en E2EZZZ, E2EMID en watchlist y tesis persistida en
// E2ETES (sqlite local: no hay endpoint de creación de tesis). El filtro
// ?q=E2E acota el índice a las cuatro para una aserción de orden estable
// que cubre los tres niveles: tesis > cartera > watchlist > resto.
test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1 to run browser tests.");

const apiSecret = process.env.RESEARCH_AUTH_SECRET ?? "cavaai-e2e-research-secret-at-least-32-characters";
const apiUser = "e2e-browser-user";
const apiBase = E2E_UI_BACKEND_URL;

function signedHeaders(method: string, path: string, body: Buffer) {
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const nonce = randomUUID().replaceAll("-", "");
  const bodyHash = createHash("sha256").update(body).digest("hex");
  const signature = createHmac("sha256", apiSecret)
    .update(`${apiUser}:${apiUser}:${timestamp}:${nonce}:${method}:${path}:${bodyHash}`)
    .digest("hex");
  return {
    "X-CavaAI-Tenant": apiUser,
    "X-CavaAI-User": apiUser,
    "X-CavaAI-Timestamp": timestamp,
    "X-CavaAI-Nonce": nonce,
    "X-CavaAI-Method": method,
    "X-CavaAI-Path": path,
    "X-CavaAI-Body-Hash": bodyHash,
    "X-CavaAI-Signature": signature,
    "Content-Type": "application/json",
  };
}

async function post(request: import("@playwright/test").APIRequestContext, path: string, payload: unknown) {
  const body = Buffer.from(JSON.stringify(payload));
  const res = await request.post(`${apiBase}${path}`, { data: body, headers: signedHeaders("POST", path, body) });
  expect(res.status(), await res.text()).toBeLessThan(300);
}

// No hay endpoint de creación de tesis (las generan los workers): la
// semilla la inserta en el sqlite local del backend e2e, mirando el
// tenant del bypass. Misma fuente que latest_thesis del snapshot.
function seedThesis(ticker: string) {
  const py = `
import sqlite3
import sys
db = sqlite3.connect(sys.argv[1])
cur = db.cursor()
tenant = cur.execute("SELECT id FROM tenants WHERE external_id = ?", ("${apiUser}",)).fetchone()
company = cur.execute("SELECT id FROM companies WHERE ticker = ?", ("${ticker}",)).fetchone()
assert company, "company ${ticker} no encontrada"
# Idempotente: un retry de Playwright reejecuta la semilla y el INSERT
# duplicado chocaba con la UNIQUE (tenant, company, version).
cur.execute("DELETE FROM thesis_versions WHERE company_id = ?", (company[0],))
cur.execute(
    "INSERT INTO thesis_versions (tenant_id, company_id, version, status, thesis_markdown, executive_summary, rating, data_confidence_score, source_coverage_score, red_team_score, valuation_risk_score, created_at, updated_at) VALUES (?, ?, 1, 'published', '# T', 'resumen', 'watch', 0, 0, 0, 0, datetime('now'), datetime('now'))",
    (tenant[0] if tenant else None, company[0]),
)
db.commit()
db.close()
`;
  execFileSync(E2E_PYTHON_BIN, ["-c", py, e2eUiDatabasePath()]);
}

test("el índice ordena tesis > cartera > watchlist > resto", async ({ page, request }) => {
  // Prefijo exclusivo E2EREL: otros specs siembran E2E* en el tenant
  // compartido (methodology-disclosure compra E2EMD1-3) y un filtro E2E
  // generico recoge sus tickers y rompe la asercion de orden.
  await post(request, "/api/companies/ensure", { ticker: "E2EREL4", name: "E2E Rel Alpha Corp" });
  await post(request, "/api/companies/ensure", { ticker: "E2EREL3", name: "E2E Rel Middle Corp" });
  await post(request, "/api/companies/ensure", { ticker: "E2EREL1", name: "E2E Rel Tesis Corp" });
  await post(request, "/api/companies/ensure", { ticker: "E2EREL2", name: "E2E Rel Zulu Corp" });
  await post(request, "/api/portfolio/transactions", {
    ticker: "E2EREL2", action: "buy", quantity: 1, price: 100, trade_date: "2026-01-15", currency: "USD", fees: 0,
  });
  await post(request, "/api/watchlist", { symbol: "E2EREL3" });
  seedThesis("E2EREL1");

  await page.goto("/research?q=E2EREL");
  await expect(page.getByRole("heading", { name: "Índice de research", level: 1 })).toBeVisible({ timeout: 60_000 });

  // La membresia (cartera/watchlist) puede tardar unos segundos en ser
  // visible para el indice; se relee con reload en vez de fallar a la
  // primera pasada.
  await expect(async () => {
    await page.reload();
    const tickers = await page.locator("ul li a .text-base").allTextContents();
    const relTickers = tickers.map((t) => t.trim()).filter((t) => t.startsWith("E2EREL"));
    expect(relTickers).toEqual(["E2EREL1", "E2EREL2", "E2EREL3", "E2EREL4"]);
  }).toPass({ timeout: 60_000, intervals: [3_000, 5_000, 10_000] });

  await page.screenshot({ path: "test-results/research-relevance.png" });
});
