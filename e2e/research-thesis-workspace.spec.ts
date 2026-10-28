import { execFileSync } from "node:child_process";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";

const runUiE2E = process.env.E2E_UI_RUN === "1";

const uiBackendURL = process.env.E2E_UI_BACKEND_URL ?? "http://127.0.0.1:8100";
const e2eResearchSecret =
  process.env.RESEARCH_AUTH_SECRET ?? "cavaai-e2e-research-secret-at-least-32-characters";

// /research/MSFT solo renderiza el workspace si la empresa existe: el spec
// asegura su propio dato en vez de depender del estado de otros specs. Firma ligada al request
// (nonce + metodo + ruta + sha256 del cuerpo), la misma que
// e2e/fixtures/research-api.ts: sirve contra backend leniente y contra
// research_auth_strict_binding=True (el default).
test.beforeAll(async () => {
  if (!runUiE2E) return;
  const path = "/api/companies/ensure";
  const body = JSON.stringify({ ticker: "MSFT", name: "Microsoft Corporation" });
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const nonce = randomUUID().replaceAll("-", "");
  const bodyHash = createHash("sha256").update(body).digest("hex");
  const signature = createHmac("sha256", e2eResearchSecret)
    .update(`e2e-api-tenant:e2e-api-user:${timestamp}:${nonce}:POST:${path}:${bodyHash}`)
    .digest("hex");
  const res = await fetch(`${uiBackendURL}${path}`, {
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
  if (!res.ok) throw new Error(`ensure MSFT fallo: ${res.status} ${await res.text()}`);

  const pathNar = "/api/companies/ensure";
  const bodyNar = JSON.stringify({ ticker: "E2ENAR", name: "E2E Narrative Corp" });
  const tsNar = Math.floor(Date.now() / 1000).toString();
  const nonceNar = randomUUID().replaceAll("-", "");
  const hashNar = createHash("sha256").update(bodyNar).digest("hex");
  const sigNar = createHmac("sha256", e2eResearchSecret)
    .update(`e2e-api-tenant:e2e-api-user:${tsNar}:${nonceNar}:POST:${pathNar}:${hashNar}`)
    .digest("hex");
  const resNar = await fetch(`${uiBackendURL}${pathNar}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-CavaAI-Tenant": "e2e-api-tenant",
      "X-CavaAI-User": "e2e-api-user",
      "X-CavaAI-Timestamp": tsNar,
      "X-CavaAI-Nonce": nonceNar,
      "X-CavaAI-Method": "POST",
      "X-CavaAI-Path": pathNar,
      "X-CavaAI-Body-Hash": hashNar,
      "X-CavaAI-Signature": sigNar,
    },
    body: bodyNar,
  });
  if (!resNar.ok) throw new Error(`ensure E2ENAR fallo: ${resNar.status} ${await resNar.text()}`);

  // Arranque limpio para el boton de generacion: la corrida E2E levanta el
  // scheduler del backend pero no un worker que consuma la cola, y cualquier
  // run de tesis encolado para MSFT (p.ej. por una corrida anterior con la
  // misma BD) acaba dispatch_failed; el boton lo refleja ocupado
  // honestamente («Generando en segundo plano…») y el spec asume estado
  // ocioso. Se borran los runs GenerateThesisWorkflow de MSFT en la BD E2E.
  execFileSync("python3", [
    "-c",
    `
import sqlite3
db = sqlite3.connect("data-engine/cavaai_ui_e2e.db")
cur = db.cursor()
ids = [r[0] for r in cur.execute(
    "SELECT id FROM workflow_runs WHERE workflow_name = 'GenerateThesisWorkflow' "
    "AND json_extract(input_payload, '$.ticker') = 'MSFT'"
)]
for rid in ids:
    cur.execute("DELETE FROM workflow_step_runs WHERE run_id = ?", (rid,))
    cur.execute("DELETE FROM workflow_runs WHERE id = ?", (rid,))
db.commit()
db.close()
`,
  ]);
});

test.describe("research thesis workspace", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test("thesis view shows honest empty states when no thesis is persisted", async ({
    page,
  }) => {
    await page.goto("/research/MSFT?view=thesis");

    // Async generation entry point is present and idle.
    await expect(
      page.getByRole("button", { name: "Generar tesis" }),
    ).toBeVisible();

    // Sin ninguna tesis no hay nada que descargar: no se pinta un botón muerto.
    await expect(page.getByRole("link", { name: /Descargar PDF/ })).toHaveCount(0);

    // Without a persisted thesis the workspace says so - nothing invented.
    await expect(page.getByText("Aún no existe ninguna tesis.")).toBeVisible();

    // Mobile intentionally starts collapsed; open the real control before checking content.
    if ((page.viewportSize()?.width ?? 1440) < 768) {
      const toggle = page.getByRole("button", { name: "Historial de versiones y aprobaciones" });
      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
    }
    // Collapsible panels open by default on desktop viewports.
    await expect(
      page.getByText("Aún no hay historial de versiones."),
    ).toBeVisible();
    await expect(page.getByText("0 versiones")).toBeVisible();
    await expect(page.getByText("0 afirmaciones")).toBeVisible();

    // The history panel states its own provenance limits.
    await expect(
      page.getByText(
        "el sistema no registra quién aprobó cada versión",
      ),
    ).toBeVisible();
  });

  test("memo renderiza la seccion Analisis narrativo persistida (y la oculta sin datos)", async ({
    page,
  }) => {
    // Semilla directa en sqlite (tenant del bypass de navegador), idempotente:
    // borra versiones previas de E2ENAR antes de insertar (retry-safe).
    const sections = JSON.stringify([
      {
        titulo: "Lo que sabemos",
        parrafos: [
          "E2ENAR cotiza a 10.00 USD frente a un escenario base de 12.00 USD (margen de seguridad del 17%).",
        ],
      },
      {
        titulo: "Salvedad",
        parrafos: ["Esto no es recomendacion de inversion (semilla e2e)."],
      },
    ]);
    const pyScript = `
import sqlite3
db = sqlite3.connect("data-engine/cavaai_ui_e2e.db")
cur = db.cursor()
tenant = cur.execute("SELECT id FROM tenants WHERE external_id = ?", ("e2e-browser-user",)).fetchone()
company = cur.execute("SELECT id FROM companies WHERE ticker = ?", ("E2ENAR",)).fetchone()
assert company, "company E2ENAR no encontrada"
cur.execute("DELETE FROM thesis_versions WHERE company_id = ?", (company[0],))
cur.execute("DELETE FROM fundamental_model_versions WHERE company_id = ?", (company[0],))
# La puerta de publicacion retiene la narrativa de una tesis 'published' sin
# modelo publicable verificado: la semilla necesita un modelo publicable.
cur.execute(
    "INSERT INTO fundamental_model_versions (tenant_id, company_id, version, engine_version, algorithm_version, framework_key, horizon_years, status, publishable, input_fingerprint, forecast_fingerprint, market_snapshot_fingerprint, valuation_snapshot_fingerprint, code_commit_sha, scenario_probabilities, model_snapshot, created_at, updated_at) VALUES (?, ?, 1, 'e2e', 'e2e', 'e2e', 10, 'final', 1, 'fp-in', 'fp-forecast', 'fp-market', 'fp-valuation', 'e2e', '{}', '{}', datetime('now'), datetime('now'))",
    (tenant[0] if tenant else None, company[0]),
)
cur.execute(
    "INSERT INTO thesis_versions (tenant_id, company_id, version, status, thesis_markdown, executive_summary, rating, data_confidence_score, source_coverage_score, red_team_score, valuation_risk_score, narrative_sections, created_at, updated_at) VALUES (?, ?, 1, 'published', '# T', 'resumen ejecutivo semilla', 'watch', 0, 0, 0, 0, ?, datetime('now'), datetime('now'))",
    (tenant[0] if tenant else None, company[0], SECTIONS_JSON),
)
db.commit()
db.close()
`.replace("SECTIONS_JSON", JSON.stringify(sections));
    execFileSync("python3", ["-c", pyScript]);

    await page.goto("/research/E2ENAR?view=thesis");
    await expect(
      page.getByRole("heading", { name: "Análisis narrativo" }),
    ).toBeVisible();
    await expect(page.getByText("Lo que sabemos")).toBeVisible();
    await expect(
      page.getByText("E2ENAR cotiza a 10.00 USD", { exact: false }),
    ).toBeVisible();
    await expect(
      page.getByText("Esto no es recomendacion de inversion (semilla e2e)."),
    ).toBeVisible();
    const narrativePanel = page.getByLabel("Análisis narrativo");
    await narrativePanel.scrollIntoViewIfNeeded();
    await narrativePanel.screenshot({
      path: "test-results/analisis-narrativo.png",
    });

    // Con versión publicada el menú "Leer / Descargar" sí existe y apunta a
    // los endpoints por ticker (la vista dedicada, el PDF y el Markdown).
    await expect(
      page.getByRole("link", { name: "Descargar PDF" }),
    ).toHaveAttribute("href", "/api/thesis/E2ENAR/pdf");
    await page.getByRole("button", { name: "Leer / Descargar" }).click();
    await expect(
      page.getByRole("menuitem", { name: "Leer la tesis" }),
    ).toHaveAttribute("href", "/research/E2ENAR/tesis");
    await expect(
      page.getByRole("menuitem", { name: "Descargar PDF" }),
    ).toHaveAttribute("href", "/api/thesis/E2ENAR/pdf");
    await expect(
      page.getByRole("menuitem", { name: "Descargar Markdown" }),
    ).toHaveAttribute("href", "/api/thesis-memo/E2ENAR");
    await page.keyboard.press("Escape");

    // Caso oculto: sin narrative_sections la seccion no aparece (honesto).
    await page.goto("/research/MSFT?view=thesis");
    await expect(
      page.getByRole("heading", { name: "Análisis narrativo" }),
    ).toHaveCount(0);
  });

  test("collapsible panels start collapsed on a 390px mobile viewport", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/research/MSFT?view=thesis");

    const emptyHistory = page.getByText("Aún no hay historial de versiones.");
    await expect(emptyHistory).toBeHidden();

    // The tap target expands the panel on demand (button + aria-expanded).
    const historyToggle = page.getByRole("button", {
      name: "Historial de versiones y aprobaciones",
    });
    await expect(historyToggle).toHaveAttribute("aria-expanded", "false");
    await historyToggle.click();
    await expect(historyToggle).toHaveAttribute("aria-expanded", "true");
    await expect(emptyHistory).toBeVisible();
  });
});
