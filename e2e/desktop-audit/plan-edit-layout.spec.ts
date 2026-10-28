import { expect, test } from "@playwright/test";
test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1");
test.use({ viewport: { width: 1440, height: 900 } });

test("editar plan: select de categoría sin truncar y primera fila alineada", async ({ page }) => {
  await page.goto("/plan", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(4000);
  // Sin plan sembrado en la BD e2e el disparador es «Configurar plan»; con
  // plan existente, «Editar plan». El diálogo es el mismo PlanSetupDialog.
  await page.getByRole("button", { name: /Editar plan|Configurar plan/ }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  // Un plan nuevo arranca con una fila: se añaden hasta tener la tercera que
  // mide el texto más largo («Clase de activo»).
  while ((await page.getByLabel(/Categoría \d+/).count()) < 3) {
    await page.getByRole("button", { name: /Añadir ticker/ }).click();
  }
  await page.getByLabel("Categoría 3", { exact: true }).selectOption("asset_class");
  const m = await page.evaluate(() => {
    const kind = document.querySelector("[aria-label='Categoría 3']") as HTMLSelectElement;
    // La tercera fila ya está en asset_class para medir el texto más largo.
    const monthly = document.getElementById("plan-monthly") as HTMLInputElement;
    const start = document.getElementById("plan-start") as HTMLInputElement;
    const horizon = document.getElementById("plan-horizon") as HTMLInputElement;
    const cs = getComputedStyle(kind);
    const ctx = document.createElement("canvas").getContext("2d")!;
    ctx.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const textW = Math.ceil(ctx.measureText("Clase de activo").width);
    return {
      kindW: kind.clientWidth,
      neededW: textW + 16 + 24,
      kindText: kind.options[kind.selectedIndex].text,
      tops: [monthly, start, horizon].map((i) => Math.round(i.getBoundingClientRect().top)),
    };
  });
  console.log("PLAN_LAYOUT=" + JSON.stringify(m));
  // «Clase de activo» debe caber: ancho del texto + padding + flecha nativa.
  expect(m.kindText).toBe("Clase de activo");
  expect(m.kindW).toBeGreaterThanOrEqual(m.neededW);
  // Los tres campos de la primera fila deben compartir línea base.
  expect(Math.max(...m.tops) - Math.min(...m.tops)).toBeLessThanOrEqual(1);
});
