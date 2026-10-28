import { expect, test } from "@playwright/test";
test.skip(process.env.E2E_UI_RUN !== "1", "Set E2E_UI_RUN=1");

for (const path of ["/knowledge", "/inversores/cartas"]) {
  test(`${path}: initial hydration preserves the library state`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => {
      if (m.type() === "error" && /hydrat|Minified React error #4(?:18|23|25)/i.test(m.text())) errors.push(m.text());
    });
    await page.setViewportSize({ width: 1024, height: 850 });
    await page.goto(path);
    const slot = page.locator("#brain-library-slot");
    let hasLibrary = true;
    if (path === "/inversores/cartas") {
      const empty = page.getByText("Todavía no hay cartas en la biblioteca.", { exact: true });
      const consult = page.locator("summary", { hasText: "Consultar la biblioteca" });
      // Wait for a real terminal state before deciding; an absent slot alone
      // is never accepted as proof of an empty library.
      await expect(empty.or(consult)).toBeVisible();
      hasLibrary = !(await empty.isVisible());
      if (hasLibrary) await consult.click();
      else {
        await expect(empty).toBeVisible();
        await expect(slot).toHaveCount(0);
      }
    }
    if (hasLibrary) {
      await expect(slot).toHaveCount(1);
      await expect(slot.getByRole("region", { name: "Cerebro GerarAI" })).toBeVisible();
      const input = page.getByLabel("Pregunta al cerebro", { exact: true });
      await input.fill("Pregunta de prueba sin enviar");
      await expect(input).toHaveValue("Pregunta de prueba sin enviar");
      await expect(page.getByRole("button", { name: "Enviar pregunta", exact: true })).toBeEnabled();
    }
    expect(errors).toEqual([]);
  });
}
