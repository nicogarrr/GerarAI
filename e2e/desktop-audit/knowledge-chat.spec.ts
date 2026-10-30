import { expect, test } from "@playwright/test";
test.skip(process.env.E2E_UI_RUN !== "1", "Set E2E_UI_RUN=1");

// Nico (30-oct): en la Biblioteca y en las cartas el Cerebro sigue el patrón
// del resto de la app: plegado abajo a la derecha, nada incrustado en mitad de
// la página; el botón de la página abre ese mismo panel flotante.
for (const path of ["/knowledge", "/inversores/cartas"]) {
  test(`${path}: Cerebro docked and collapsed, opens on demand with the library context`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => {
      if (m.type() === "error" && /hydrat|Minified React error #4(?:18|23|25)/i.test(m.text())) errors.push(m.text());
    });
    await page.setViewportSize({ width: 1024, height: 850 });
    await page.goto(path);
    await expect(page.locator("#brain-library-slot")).toHaveCount(0);
    await expect(page.getByRole("dialog", { name: "Cerebro GerarAI" })).toHaveCount(0);
    const trigger = page.getByRole("button", { name: "Abrir el cerebro" });
    await expect(trigger).toBeVisible();
    let entry = page.getByRole("button", { name: "Preguntar a la biblioteca" });
    if (path === "/inversores/cartas") {
      const empty = page.getByText("Todavía no hay cartas en la biblioteca.", { exact: true });
      entry = page.getByRole("button", { name: "Preguntar a las cartas" });
      await expect(empty.or(entry)).toBeVisible();
      if (await empty.isVisible()) {
        expect(errors).toEqual([]);
        return;
      }
    }
    await entry.click();
    const dialog = page.getByRole("dialog", { name: "Cerebro GerarAI" });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("Doctrina, no datos actuales de empresas");
    const input = page.getByLabel("Pregunta al cerebro", { exact: true });
    await input.fill("Pregunta de prueba sin enviar");
    await expect(input).toHaveValue("Pregunta de prueba sin enviar");
    await expect(page.getByRole("button", { name: "Enviar pregunta", exact: true })).toBeEnabled();
    expect(errors).toEqual([]);
  });
}
