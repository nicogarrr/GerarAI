import { createHash, createHmac, randomUUID } from "node:crypto";
import { expect, type Locator, type Page, test } from "@playwright/test";

// Hallazgos QA de la ficha (Nico, 2026-10-19):
//  (6) 390px: el enlace "Ver la evaluación del foso" se pintaba encima del
//      titulo "Calidad financiera según la empresa".
// (10) 1280px: la barra de 9 modulos desbordaba con scrollbar horizontal.
test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1 to run browser tests.");

const uiBackendURL = process.env.E2E_UI_BACKEND_URL ?? "http://127.0.0.1:8100";
const e2eResearchSecret =
  process.env.RESEARCH_AUTH_SECRET ?? "cavaai-e2e-research-secret-at-least-32-characters";

// Firma ligada al request (misma que e2e/fixtures/research-api.ts). La UI en
// E2E (E2E_AUTH_BYPASS) llama al backend con tenant = user.id =
// "e2e-browser-user" (ver lib/auth/research-identity.ts): el fixture debe
// sembrarse en ESE tenant o la pagina no vera nunca lo que persiste el test.
const uiTenant = "e2e-browser-user";
async function signedPost(path: string, payload?: unknown): Promise<Response> {
  const body = payload === undefined ? "" : JSON.stringify(payload);
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const nonce = randomUUID().replaceAll("-", "");
  const bodyHash = createHash("sha256").update(body).digest("hex");
  const signature = createHmac("sha256", e2eResearchSecret)
    .update(`${uiTenant}:${uiTenant}:${timestamp}:${nonce}:POST:${path}:${bodyHash}`)
    .digest("hex");
  return fetch(`${uiBackendURL}${path}`, {
    method: "POST",
    headers: {
      ...(body ? { "content-type": "application/json" } : {}),
      "X-CavaAI-Tenant": uiTenant,
      "X-CavaAI-User": uiTenant,
      "X-CavaAI-Timestamp": timestamp,
      "X-CavaAI-Nonce": nonce,
      "X-CavaAI-Method": "POST",
      "X-CavaAI-Path": path,
      "X-CavaAI-Body-Hash": bodyHash,
      "X-CavaAI-Signature": signature,
    },
    body: body || undefined,
  });
}

// Captura el panel completo con 100 px de contexto arriba y abajo, en
// coordenadas de DOCUMENTO (rect de viewport + scroll), para que no se desplace.
async function capturarPanel(page: Page, panel: Locator, nombre: string): Promise<void> {
  await panel.scrollIntoViewIfNeeded();
  const caja = await panel.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { x: 0, y: r.top + window.scrollY, h: r.height };
  });
  const top = Math.max(0, caja.y - 100);
  await page.screenshot({
    path: `test-results/${nombre}.png`,
    fullPage: true,
    clip: { x: 0, y: top, width: 390, height: caja.y + caja.h + 100 - top },
  });
}

async function ensureCompany(ticker: string, name: string): Promise<void> {
  const res = await signedPost("/api/companies/ensure", { ticker, name });
  if (!res.ok) throw new Error(`ensure ${ticker} fallo: ${res.status} ${await res.text()}`);
}

test.describe("ficha: panel de calidad financiera", () => {
  test("con score MOAT persistido (fixture real): enlace presente y sin solape a 390px", async ({ page }) => {
    await ensureCompany("MSFT", "Microsoft Corporation");
    // Calcula y PERSISTE las metricas reales de la empresa, incluida
    // quality_moat_score_v2: es lo que lee el panel (sin atajos en el test).
    const refresh = await signedPost("/api/companies/MSFT/metrics/refresh");
    if (!refresh.ok) throw new Error(`refresh MSFT fallo: ${refresh.status} ${await refresh.text()}`);
    const refreshed = (await refresh.json()) as { metrics: Array<{ metric: string }> };
    expect(refreshed.metrics.some((m) => m.metric === "quality_moat_score_v2")).toBe(true);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/research/MSFT");
    await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const panel = page.locator("section", { has: page.getByRole("heading", { name: "Calidad financiera según la empresa" }) });
    await expect(panel).toHaveCount(1);
    const titulo = panel.getByRole("heading", { name: "Calidad financiera según la empresa" });
    const accion = panel.getByRole("link", { name: "Ver la evaluación del foso" });
    await expect(titulo).toBeVisible();
    // Sin silencio: si falta el enlace, el test falla.
    await expect(accion).toHaveCount(1);
    await expect(accion).toBeVisible();
    const a = await titulo.boundingBox();
    const b = await accion.boundingBox();
    expect(a && b).toBeTruthy();
    // Evidencia visual (artefacto de CI) y numeros reales de las cajas.
    console.log(`MOAT 390px titulo=${JSON.stringify(a)} enlace=${JSON.stringify(b)}`);
    await capturarPanel(page, panel, "ficha-moat-colapsado-390");
    // En movil el panel arranca plegado: se expande como lo haria el usuario.
    await panel.getByRole("button", { name: /Expandir Calidad financiera/ }).click();
    await expect(panel.getByRole("button", { name: /Contraer Calidad financiera/ })).toBeVisible();
    await capturarPanel(page, panel, "ficha-moat-expandido-390");
    const solapan =
      a!.x < b!.x + b!.width && b!.x < a!.x + a!.width && a!.y < b!.y + b!.height && b!.y < a!.y + a!.height;
    expect(solapan, `titulo ${JSON.stringify(a)} vs accion ${JSON.stringify(b)}`).toBe(false);
  });

  test("sin score MOAT: estado vacio honesto y sin enlace de detalle", async ({ page }) => {
    // Empresa sin metricas calculadas: el panel debe decirlo, no ocultarse.
    await ensureCompany("NOMOAT", "Sin Foso Calculado SA");
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/research/NOMOAT");
    await expect(page.getByRole("heading", { name: "NOMOAT", level: 1 })).toBeVisible();
    const panel = page.locator("section", { has: page.getByRole("heading", { name: "Calidad financiera según la empresa" }) });
    await expect(panel).toHaveCount(1);
    await expect(panel.getByRole("link", { name: "Ver la evaluación del foso" })).toHaveCount(0);
    const vacio = panel.getByText("Sin evaluación de calidad generada todavía");
    await expect(vacio).toBeAttached();
    await capturarPanel(page, panel, "ficha-nomoat-colapsado-390");
    // Plegado en movil no se ve: se expande como lo haria el usuario y debe verse.
    await panel.getByRole("button", { name: /Expandir Calidad financiera/ }).click();
    await expect(vacio).toBeVisible();
    await capturarPanel(page, panel, "ficha-nomoat-expandido-390");
  });
});

test("1280px: la fila de pestañas no necesita scroll horizontal", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/research/MSFT");
  await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
  // Una sola fila de seis pestañas (29-oct-2026): ya no hay fila de módulos.
  const nav = page.getByRole("navigation", { name: "Secciones de la empresa", exact: true });
  await expect(nav).toBeVisible();
  const medidas = await nav.evaluate((el) => ({ scroll: el.scrollWidth, cliente: el.clientWidth }));
  console.log(`fila de pestañas a 1280px: scrollWidth=${medidas.scroll} clientWidth=${medidas.cliente}`);
  expect(medidas.scroll).toBeLessThanOrEqual(medidas.cliente + 1);
});
