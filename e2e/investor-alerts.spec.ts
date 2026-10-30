import { expect, test } from "@playwright/test";

const runUiE2E = process.env.E2E_UI_RUN === "1";

test.describe("investor alerts flow", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test("alerts list every row with a research link", async ({ page }) => {
    await page.goto("/alerts");

    await expect(page.getByRole("heading", { name: "Alertas", level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name: "Nueva alerta" })).toBeVisible();

    const researchLinks = page.getByRole("link", { name: /Ver research/ });
    if ((await researchLinks.count()) === 0) {
      await expect(page.getByText("No tienes alertas configuradas")).toBeVisible();
      return;
    }

    // Every alert row must link to /research/[symbol].
    const count = await researchLinks.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count; i += 1) {
      await expect(researchLinks.nth(i)).toHaveAttribute("href", /\/research\/[^/]+$/);
    }
  });

  test("new alert dialog opens with symbol and create controls", async ({ page }) => {
    await page.goto("/alerts");

    await page.getByRole("button", { name: "Nueva alerta" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Crear alerta" })).toBeVisible();
    await expect(page.getByLabel("Símbolo")).toBeVisible();
    await expect(page.getByRole("button", { name: "Crear alerta" })).toBeVisible();
  });
});
