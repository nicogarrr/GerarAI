import { expect, test } from "@playwright/test";

const runUiE2E = process.env.E2E_UI_RUN === "1";

// The API-level evidence specs (research-evidence-flow) cover data-engine document
// ingest/claims/chat. These specs cover the gap: the Knowledge Library UI
// (upload form + document list) which no existing e2e spec touches.
test.describe("investor knowledge flow", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test("knowledge upload form and document list render", async ({ page }) => {
    // La página se dividió en pestañas (Biblioteca / Principios / Subir) con el
    // estado en la URL, así que el formulario de subida ya no está en la vista
    // por defecto: hay que ir a ?tab=subir.
    await page.goto("/knowledge?tab=subir");

    await expect(
      page.getByRole("heading", { name: "Biblioteca", level: 1 }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Subir conocimiento" })).toBeVisible();
    await expect(page.getByPlaceholder("Título del documento")).toBeVisible();
    // F142: el input file nativo queda sr-only; el disparador visible es el
    // label «Elegir archivo» con el estado «Ningún archivo seleccionado».
    await expect(page.getByText("Elegir archivo").first()).toBeVisible();
    await expect(page.getByText("Ningún archivo seleccionado").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Subir", exact: true })).toBeVisible();

    // El listado (y su estado vacío) vive en la pestaña Biblioteca: en una
    // página con pestañas server-rendered solo el contenido de la pestaña
    // activa está en el DOM, así que el chequeo de vacío va tras navegar.
    await page.goto("/knowledge");

    // Esperar al estado terminal de la lista (vacía o con documentos) ANTES de
    // decidir: un isVisible()/count() de una sola lectura corre contra la página
    // aun renderizando y ve «0 enlaces» aunque los documentos lleguen un instante
    // despues (fallo visto en CI sobre un commit que no toca esta pagina).
    const emptyState = page.getByText("No hay documentos en esta página.");
    // Listed documents expose chunk browsing and principle extraction per row.
    const chunksLinks = page.getByRole("link", { name: "Fragmentos" });
    await expect(emptyState.or(chunksLinks.first())).toBeVisible({ timeout: 15_000 });
    if (await emptyState.isVisible()) {
      return;
    }

    expect(await chunksLinks.count()).toBeGreaterThan(0);
    await expect(chunksLinks.first()).toHaveAttribute("href", /\/knowledge\?document=\d+/);
    await expect(page.getByRole("button", { name: "Extraer" }).first()).toBeVisible();
  });

  test("knowledge upload ingests a document and lists it", async ({ page }) => {
    const marker = `e2e-knowledge-${Date.now()}`;
    const title = `E2E investing notes ${marker}`;

    await page.goto("/knowledge?tab=subir");
    const uploadForm = page.locator("form", { has: page.getByPlaceholder("Título del documento") });
    await uploadForm.getByPlaceholder("Título del documento").fill(title);
    await uploadForm.locator('input[type="file"]').setInputFiles({
      name: `${marker}.txt`,
      mimeType: "text/plain",
      buffer: Buffer.from(
        `Inversor E2E ${marker}: comprar calidad con margen de seguridad y paciencia.`,
      ),
    });
    await uploadForm.getByRole("button", { name: "Subir", exact: true }).click();

    await expect(page.getByText("Documento ingerido")).toBeVisible({ timeout: 30_000 });

    await page.goto("/knowledge");
    await expect(page.getByText(title).filter({ visible: true }).first()).toBeVisible({ timeout: 30_000 });
  });

  test("knowledge upload reset clears the visible filename (F142)", async ({ page }) => {
    const marker = `e2e-knowledge-reset-${Date.now()}`;
    const title = `E2E reset notes ${marker}`;

    await page.goto("/knowledge?tab=subir");
    const uploadForm = page.locator("form", { has: page.getByPlaceholder("Título del documento") });
    await uploadForm.getByPlaceholder("Título del documento").fill(title);
    await uploadForm.locator('input[type="file"]').setInputFiles({
      name: `${marker}.txt`,
      mimeType: "text/plain",
      buffer: Buffer.from(`E2E reset ${marker}: archivo de prueba.`),
    });
    // Tras elegirlo, el nombre es visible junto al disparador.
    await expect(page.getByText(`${marker}.txt`)).toBeVisible();
    await uploadForm.getByRole("button", { name: "Subir", exact: true }).click();
    await expect(page.getByText("Documento ingerido")).toBeVisible({ timeout: 30_000 });
    // El form.reset() de MutationForm tras la subida limpia el input nativo;
    // el estado visible debe sincronizarse (F142).
    await expect(page.getByText("Ningún archivo seleccionado")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(`${marker}.txt`)).toBeHidden();
  });
});
