import { expect, test } from "@playwright/test";

const runUiE2E = process.env.E2E_UI_RUN === "1";

test.describe("investor thesis alert flow", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test("research thesis exposes the quick alert control", async ({ page }) => {
    await page.goto("/research/MSFT");

    await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
    // El formulario de alerta vive en un popover tras el botón campana.
    await page.getByRole("button", { name: "Alerta de precio" }).click();
    await expect(page.getByPlaceholder("Precio objetivo $")).toBeVisible();
    await expect(page.getByRole("button", { name: "+ Alerta" })).toBeVisible();

    const alertsLink = page.getByRole("link", { name: "Ver alertas" });
    await expect(alertsLink).toBeVisible();
    await expect(alertsLink).toHaveAttribute("href", "/alerts");
  });

  test("quick alert validates the target price client-side", async ({ page }) => {
    await page.goto("/research/MSFT");

    await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
    await page.getByRole("button", { name: "Alerta de precio" }).click();
    await page.getByRole("button", { name: "+ Alerta" }).click();
    await expect(page.getByText("Introduce un precio objetivo válido")).toBeVisible();
  });
});
