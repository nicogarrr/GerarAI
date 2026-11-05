import { test, expect } from "@playwright/test";
import { waitForHydration } from "../fixtures/wait-for-hydration";
test.skip(process.env.E2E_UI_RUN !== "1", "Set E2E_UI_RUN=1");

test("plan: dialog shows the complete exchange-qualified target at 1024px", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 850 });
  await page.goto("/plan");
  // El disparador es SSR y visible antes de hidratar (React 19): clicarlo antes
  // de tiempo se traga el evento (data-state queda closed y el dialog nunca
  // abre, visto en CI #4680 con los chunks de traducción aún descargando).
  await waitForHydration(page);
  // No seeded account or saved plan needed, and absence must fail, not pass.
  await page.getByRole("button", { name: /Editar plan|Configurar plan/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  const target = dialog.getByLabel("Objetivo 1", { exact: true });
  await target.fill("SAN.MC");
  await expect(target).toHaveValue("SAN.MC");
  const sizes = await target.evaluate((input) => {
    const style = getComputedStyle(input);
    const ctx = document.createElement("canvas").getContext("2d")!;
    ctx.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
    return {
      available: input.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
      text: ctx.measureText((input as HTMLInputElement).value).width,
    };
  });
  expect(sizes.available, "full SAN.MC text fits inside input padding").toBeGreaterThanOrEqual(sizes.text);
});
