import { expect, expectHealthyPage, runUiE2E, test, VIEWPORTS, visit } from "./support";

for (const vp of VIEWPORTS) {
  test.describe(`404 y Cerebro (${vp.name})`, () => {
    test.skip(!runUiE2E, "Set E2E_UI_RUN=1 E2E_USER_FLOWS=1 to run the user-flow suite.");
    test.use(vp.use);

    test("una ruta inexistente da la página 404 con salidas", async ({ page, health }) => {
      health.allowResponse(/\/no-existe-e2e-flujos$/, 404);
      const response = await visit(page, "/no-existe-e2e-flujos");
      expect(response?.status()).toBe(404);
      await expect(page.getByRole("heading", { name: "Página no encontrada", level: 1 })).toBeVisible();
      await expect(page.getByRole("link", { name: "Volver al inicio" })).toHaveAttribute("href", "/");
      await expectHealthyPage(page, "404");
      await page.getByRole("link", { name: "Volver al inicio" }).click();
      await expect(page).not.toHaveURL(/no-existe-e2e-flujos/);
    });

    test("el Cerebro se abre y pinta su panel (LLM simulado, sin enviar nada)", async ({ page }) => {
      // Nada del Cerebro puede llegar a un modelo real: el asistente de
      // research se responde con un stub, y abrir el panel no puede disparar
      // ninguna server action (el chat va por chatWithPortfolio).
      const llmCalls: string[] = [];
      await page.route(/\/api\/research\/assistant/, async (route) => {
        llmCalls.push(route.request().url());
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "unavailable" }) });
      });
      await visit(page, "/inicio");
      const open = page.getByRole("button", { name: "Abrir el cerebro" }).first();
      await expect(open).toBeVisible();
      page.on("request", (req) => {
        if (req.method() === "POST" && req.headers()["next-action"]) llmCalls.push(`server-action ${req.url()}`);
      });
      await open.click();
      const panel = page.getByRole("dialog").or(page.getByRole("complementary")).filter({ hasText: /Cerebro|cerebro/ }).first();
      await expect(panel).toBeVisible({ timeout: 20_000 });
      await expect(panel.getByRole("textbox").first()).toBeVisible();
      await expectHealthyPage(page, "Cerebro abierto");
      await page.keyboard.press("Escape");
      await expect(panel).toBeHidden({ timeout: 10_000 });
      // Abrir no envía nada al modelo.
      expect(llmCalls).toEqual([]);
    });
  });
}
