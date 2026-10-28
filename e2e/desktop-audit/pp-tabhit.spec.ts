import { test, expect } from "@playwright/test";
test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1");

// Regresion: la TabsList con sm:h-9 fija cortaba la segunda fila envuelta;
// las tabs «Paper trading» y «Radar global» quedaban invisibles e
// inclicables bajo el contenido a 1024px.
for (const width of [1024, 1280]) {
  test(`propicks tabs clicables ${width}px`, async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/propicks", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3500);
    const d = await page.evaluate(() => {
      const tabs = [...document.querySelectorAll('[role="tab"]')];
      return tabs.map((t) => {
        const r = t.getBoundingClientRect();
        const el = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        return { text: t.textContent?.trim(), hit: el === t || t.contains(el) };
      });
    });
    console.log(`HIT ${width} ` + JSON.stringify(d));
    expect(d.length).toBeGreaterThanOrEqual(7);
    for (const t of d) expect(t.hit, `${t.text} clickable`).toBe(true);
  });
}
