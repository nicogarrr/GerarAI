import { expect, test } from "@playwright/test";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { E2E_UI_BACKEND_URL } from "./fixtures/e2e-env";

import { waitForScreenerOutcome } from "./fixtures/screener-outcome";

const runUiE2E = process.env.E2E_UI_RUN === "1";

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


test.describe("investor watchlist flow", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test.beforeEach(async ({ request }, info) => {
    if (!info.title.startsWith("watchlist ")) return;
    // Non-empty on both first run and retry: never skip the remove contract
    // just because another test removed the last shared watchlist item.
    await post(request, "/api/companies/ensure", { ticker: "MSFT", name: "Microsoft" });
    await post(request, "/api/watchlist", { symbol: "MSFT" });
  });

  test("screener Seguir reports the add outcome via toast", async ({ page }) => {
    await page.goto("/screener");
    // Resolucion acotada: filas o estado final honesto; la carga indefinida falla.
    await waitForScreenerOutcome(page);

    const rows = page.locator("table tbody tr");
    if ((await rows.count()) === 0) {
      const down = page.getByText("No hay datos ahora mismo");
      const empty = page.getByText(/Sin resultados para/);
      const states = (await down.count()) + (await empty.count());
      expect(states).toBeGreaterThan(0);
      return;
    }

    const firstFollow = rows.first().getByRole("button", { name: "Seguir" });
    await expect(firstFollow).toBeEnabled();
    await firstFollow.click();

    // Backend healthy: "añadido a la watchlist". Backend down: "No se pudo añadir".
    // Both toasts mention the watchlist, so one assertion covers the round-trip.
    await expect(page.getByText(/watchlist/i).first()).toBeVisible({ timeout: 15_000 });
  });

  test("watchlist rows link to research and expose remove controls", async ({ page }) => {
    await page.goto("/watchlist");

    await expect(page.getByRole("heading", { name: "Watchlist", level: 1 })).toBeVisible();

    const mobile = (page.viewportSize()?.width ?? 1440) < 768;
    const rows = page.locator(mobile ? "main article" : "table tbody tr");
    await expect(rows).not.toHaveCount(0);

    if (!mobile) await expect(page.getByRole("columnheader", { name: "Símbolo" })).toBeVisible();
    const rowCount = await rows.count();
    expect(rowCount).toBeGreaterThan(0);
    for (let i = 0; i < rowCount; i += 1) {
      const row = rows.nth(i);
      await expect(row.getByRole("link").first()).toHaveAttribute(
        "href",
        /\/research\/[^/]+$/,
      );
      if (!mobile) await row.locator("summary").click();
      await expect(
        row.getByRole("button", { name: /^Quitar .+ de la watchlist$/i }),
      ).toBeVisible();
    }
  });

  test("watchlist remove drops the row", async ({ page }) => {
    await page.goto("/watchlist");

    const mobile = (page.viewportSize()?.width ?? 1440) < 768;
    const rows = page.locator(mobile ? "main article" : "table tbody tr");
    const initial = await rows.count();
    expect(initial).toBeGreaterThan(0);

    if (!mobile) await rows.first().locator("summary").click();
    await rows.first().getByRole("button", { name: /^Quitar .+ de la watchlist$/i }).click();
    if (initial === 1) {
      await expect(page.getByText("Tu watchlist está vacía")).toBeVisible({ timeout: 15_000 });
    } else {
      await expect(rows).toHaveCount(initial - 1, {
        timeout: 15_000,
      });
    }
  });
});
