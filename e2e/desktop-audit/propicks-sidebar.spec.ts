import { test } from "@playwright/test";
test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1");

for (const width of [1024, 1280]) {
  test(`propicks sidebar ${width}px`, async ({ page }) => {
    test.setTimeout(90000);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/propicks", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(4000);
    // a 1024 el panel arranca colapsado: abrirlo por el toggle
    const toggle = page.getByRole("button", { name: /mostrar filtros|ocultar filtros/i });
    const toggleVisible = await toggle.isVisible().catch(() => false);
    if (toggleVisible) {
      await toggle.click();
      await page.waitForTimeout(400);
    }
    const data = await page.evaluate(() => {
      const out: Record<string, unknown> = {};
      const aplicar = [...document.querySelectorAll("button")].find((b) => b.textContent?.includes("Aplicar Filtros"));
      const actualizar = [...document.querySelectorAll("button")].find((b) => b.textContent?.includes("Actualizar selección"));
      for (const [k, b] of [["aplicar", aplicar], ["actualizar", actualizar]] as const) {
        if (!b) { out[k] = null; continue; }
        const r = b.getBoundingClientRect();
        out[k] = { clientW: b.clientWidth, scrollW: b.scrollWidth, visible: r.width > 0, right: Math.round(r.right) };
      }
      const el = document.scrollingElement ?? document.documentElement;
      out.page = { scrollW: el.scrollWidth, clientW: el.clientWidth };
      return out;
    });
    console.log(`PPSB ${width} ` + JSON.stringify({ toggleVisible, ...data }));
    if (width === 1024) {
      await page.addStyleTag({ content: "nextjs-portal{display:none!important}" });
      await page.screenshot({ path: "/tmp/shots/pp_after_1024.png", fullPage: true });
    }
  });
}
