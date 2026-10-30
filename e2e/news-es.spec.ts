import { expect, test } from "@playwright/test";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { E2E_UI_BACKEND_URL } from "./fixtures/e2e-env";

// Quick win UX 4: la ficha y las tarjetas de research leen sector/industria
// en español (nunca «Information Technology» cruda). Capturas para el OK
// visual; el titular SEC español lo cubre test_sec_connector_title_es.py
// (el conector no es alcanzable desde el stack de navegador).
test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1 to run browser tests.");

// La ingesta vive SOLO en el backend FastAPI: en modo UI el baseURL de
// Playwright es el frontend y un POST relativo a /api/news/ingest cae en
// Next (404). Semilla firmada contra el backend e2e (patron
// research-relevance / f339).
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

test("cabecera de la ficha sin sector en inglés", async ({ page }) => {
  await page.goto("/research/MSFT");

  await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
  await expect(page.getByText("Information Technology")).toHaveCount(0);
  await page.screenshot({ path: "test-results/news-es-ficha-header.png" });
});

test("tarjetas de /research sin sector en inglés", async ({ page }) => {
  await page.goto("/research");

  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByText("Information Technology")).toHaveCount(0);
  await page.screenshot({ path: "test-results/news-es-research-cards.png" });
});

// Procedencia: un titular SEC generado por GerarAI (headline_from_source=false)
// no repite el ticker como prefijo — la UI muestra el título recortado y la
// API expone el flag que lo gobierna.
test("titular sintético SEC sin prefijo de ticker duplicado", async ({ page, request }) => {
  // La API expone el ticker desde la empresa enlazada: sin ficha E2ESEC el
  // evento sale con ticker null y la UI no recorta el prefijo (no sabe cuál).
  const ensureBody = Buffer.from(
    JSON.stringify({ ticker: "E2ESEC", name: "E2E SEC Corp" })
  );
  const ensure = await request.post(`${apiBase}/api/companies/ensure`, {
    data: ensureBody,
    headers: signedHeaders("POST", "/api/companies/ensure", ensureBody),
  });
  expect(ensure.status(), await ensure.text()).toBeLessThan(300);

  const url = `https://www.sec.gov/Archives/edgar/data/320193/e2e-strip-${Date.now()}.htm`;
  const payload = {
    source: "sec_filing",
    items: [
      {
        ticker: "E2ESEC",
        title: "E2ESEC 8-K presentado ante la SEC (strip e2e)",
        summary: "E2ESEC 8-K presentado ante la SEC (strip e2e)",
        url,
        headline_from_source: false,
      },
    ],
  };
  const body = Buffer.from(JSON.stringify(payload));
  const ingestion = await request.post(`${apiBase}/api/news/ingest`, {
    data: body,
    headers: signedHeaders("POST", "/api/news/ingest", body),
  });
  expect(ingestion.status(), await ingestion.text()).toBeLessThan(300);

  await page.goto("/research/news");
  // La caché del feed puede servir la lista previa unos segundos: reintentar
  // con recarga hasta ver la fila sembrada.
  await expect(async () => {
    await page.reload();
    await expect(
      page
        .getByText("8-K presentado ante la SEC (strip e2e)", { exact: true })
        .filter({ visible: true })
        .first()
    ).toBeVisible();
  }).toPass({ intervals: [2_000, 5_000, 10_000], timeout: 30_000 });
  // El compuesto con prefijo nunca se renderiza para esta fila.
  await expect(page.getByText("E2ESEC 8-K presentado ante la SEC (strip e2e)")).toHaveCount(0);
  await page.screenshot({ path: "test-results/news-es-sec-title-strip.png" });
});
