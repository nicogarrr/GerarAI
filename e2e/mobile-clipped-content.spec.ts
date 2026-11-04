import { createHash, createHmac, randomUUID } from "node:crypto";

import { expect, test, type Page } from "@playwright/test";

import { E2E_UI_BACKEND_URL } from "./fixtures/e2e-env";

const runUiE2E = process.env.E2E_UI_RUN === "1";
const e2eResearchSecret =
  process.env.RESEARCH_AUTH_SECRET ?? "cavaai-e2e-research-secret-at-least-32-characters";

// iPhone 14 viewport: 390x844 con táctil.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

// Por qué este spec y no solo `scrollWidth <= innerWidth`: los <main> de
// inicio, watchlist, screener, búsqueda y biblioteca llevan `overflow-x-clip`.
// Con eso la página nunca desborda (scrollWidth == innerWidth) aunque una
// tarjeta mida el doble que la pantalla: lo que sobra se recorta y no hay
// forma de leerlo. Aquí se mide eso: ningún elemento visible puede acabar más
// allá del borde derecho de la pantalla recortado por un ancestro
// overflow hidden/clip. Lo que vive dentro de un contenedor con scroll
// horizontal propio (tablas con overflow-x-auto, carruseles) es alcanzable y
// no cuenta.
async function clippedBeyondViewport(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const describe = (el: Element) => {
      const b = el.getBoundingClientRect();
      const cls = typeof el.className === "string" ? el.className.slice(0, 80) : "";
      const text = ((el as HTMLElement).innerText ?? "").slice(0, 40).replace(/\n/g, " ");
      return `${el.tagName.toLowerCase()}.${cls} [${Math.round(b.left)},${Math.round(b.right)}] "${text}"`;
    };
    const out: string[] = [];
    for (const el of Array.from(document.querySelectorAll("main *"))) {
      const b = el.getBoundingClientRect();
      if (b.width <= 2 || b.height <= 2 || b.right <= vw + 1) continue;
      const style = getComputedStyle(el);
      if (style.visibility === "hidden" || style.position === "fixed") continue;
      // Solo el elemento más externo que se sale: sus hijos repetirían el aviso.
      const parent = el.parentElement;
      if (parent && parent.getBoundingClientRect().right > vw + 1 && parent.tagName !== "MAIN") continue;
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const ox = getComputedStyle(p).overflowX;
        if (ox === "auto" || ox === "scroll") break;
        if ((ox === "hidden" || ox === "clip") && p.getBoundingClientRect().right <= vw + 1) {
          out.push(`${describe(el)} recortado por ${p.tagName.toLowerCase()}`);
          break;
        }
      }
      if (out.length >= 8) break;
    }
    return out;
  });
}

async function signedEnsure(ticker: string, name: string) {
  const path = "/api/companies/ensure";
  const body = JSON.stringify({ ticker, name });
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const nonce = randomUUID().replaceAll("-", "");
  const bodyHash = createHash("sha256").update(body).digest("hex");
  const signature = createHmac("sha256", e2eResearchSecret)
    .update(`e2e-api-tenant:e2e-api-user:${timestamp}:${nonce}:POST:${path}:${bodyHash}`)
    .digest("hex");
  const res = await fetch(`${E2E_UI_BACKEND_URL}${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-CavaAI-Tenant": "e2e-api-tenant",
      "X-CavaAI-User": "e2e-api-user",
      "X-CavaAI-Timestamp": timestamp,
      "X-CavaAI-Nonce": nonce,
      "X-CavaAI-Method": "POST",
      "X-CavaAI-Path": path,
      "X-CavaAI-Body-Hash": bodyHash,
      "X-CavaAI-Signature": signature,
    },
    body,
  });
  if (!res.ok) throw new Error(`ensure ${ticker} fallo: ${res.status} ${await res.text()}`);
}

const MAIN_ROUTES = [
  "/inicio",
  "/portfolio",
  "/watchlist",
  "/research/AAPL",
  "/alerts",
  "/taxes",
  "/screener",
  "/search",
];

test.describe("móvil 390px: nada se recorta fuera de la pantalla", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test.beforeAll(async () => {
    if (!runUiE2E) return;
    await signedEnsure("AAPL", "Apple Inc.");
  });

  for (const route of MAIN_ROUTES) {
    test(`${route} no recorta contenido a la derecha`, async ({ page }) => {
      await page.goto(route);
      await expect(page.locator("main").first()).toBeVisible();
      await page.waitForLoadState("networkidle").catch(() => {});
      expect(await clippedBeyondViewport(page), `${route}: contenido recortado fuera de la pantalla`).toEqual([]);
    });
  }

  test("biblioteca: un fragmento con tabla y texto largo se lee entero", async ({ page }) => {
    const marker = `e2e-movil-${Date.now()}`;
    const markdown = [
      "# Resultados",
      "",
      `Ver https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/${marker}_10K_annual_report_full_text.htm y TOKEN_SIN_ESPACIOS_MUY_LARGO_PARA_PROBAR_EL_CORTE_DE_LOS_FRAGMENTOS.`,
      "",
      "| Año | Ingresos | EBIT | Margen | FCF | Deuda neta | Acciones | BPA |",
      "|---|---|---|---|---|---|---|---|",
      "| 2023 | 211.915 | 88.523 | 41,8 % | 59.475 | -12.000 | 7.446 | 9,68 |",
      "| 2024 | 245.122 | 109.433 | 44,6 % | 74.071 | -9.000 | 7.469 | 11,80 |",
      "",
      "Texto normal de relleno para el fragmento. ".repeat(20),
    ].join("\n");

    await page.goto("/knowledge?tab=subir");
    const uploadForm = page.locator("form", { has: page.getByPlaceholder("Título del documento") });
    await uploadForm.getByPlaceholder("Título del documento").fill(`Notas ${marker}`);
    await uploadForm.locator('input[type="file"]').setInputFiles({
      name: `${marker}.md`,
      mimeType: "text/markdown",
      buffer: Buffer.from(markdown),
    });
    await uploadForm.getByRole("button", { name: "Subir", exact: true }).click();

    // El listado pinta tabla (escritorio) y tarjetas (móvil): el enlace del
    // título lleva el id del documento en las dos; basta con que exista.
    await page.goto(`/knowledge?q=${encodeURIComponent(marker)}`);
    const titleLink = page.locator('a[href*="document="]', { hasText: `Notas ${marker}` }).first();
    await expect(titleLink).toBeAttached({ timeout: 30_000 });
    const href = await titleLink.getAttribute("href");
    expect(href).toBeTruthy();
    await page.goto(href!);
    await expect(page.getByText("TOKEN_SIN_ESPACIOS", { exact: false }).first()).toBeAttached({ timeout: 15_000 });
    await page.waitForLoadState("networkidle").catch(() => {});

    expect(await clippedBeyondViewport(page), "fragmento recortado fuera de la pantalla").toEqual([]);
  });
});
