import { test, expect } from "@playwright/test";
test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1");

// Regresion: la tabla de documentos de /knowledge no tenia padding horizontal
// entre columnas (cabeceras pegadas) y las acciones+estado quedaban cortadas
// por el scroll interno a 1024px.
for (const width of [768, 1024]) {
  test(`knowledge tabla ${width}px`, async ({ page }) => {
    test.setTimeout(75000);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/knowledge", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(4000);
    const d = await page.evaluate(() => {
      const table = document.querySelector("table");
      if (!table) return null;
      const region = table.closest("div[role='region']") ?? table.parentElement!;
      const ths = [...table.querySelectorAll("thead th")].map((th) => {
        const range = document.createRange();
        range.selectNodeContents(th);
        const tx = range.getBoundingClientRect();
        const r = th.getBoundingClientRect();
        return { text: th.textContent, textRight: Math.round(tx.right), nextCellLeft: 0, cellLeft: Math.round(r.left) };
      });
      const collisions: string[] = [];
      for (let i = 0; i < ths.length - 1; i++) {
        const gap = ths[i + 1].cellLeft - ths[i].textRight;
        if (gap < 8) collisions.push(`${ths[i].text}/${ths[i + 1].text} gap=${gap}`);
      }
      const status = table.querySelector("p[role='status']");
      const sr = status?.getBoundingClientRect();
      const rr = region.getBoundingClientRect();
      return {
        tableW: Math.round(table.getBoundingClientRect().width),
        tableScrollW: table.scrollWidth,
        regionClientW: (region as HTMLElement).clientWidth,
        collisions,
        status: sr ? { right: Math.round(sr.right), clipped: sr.right > rr.right + 1, text: status!.textContent } : null,
      };
    });
    console.log(`KT ${width} ` + JSON.stringify(d));
    expect(d).not.toBeNull();
    expect(d!.collisions, "cabeceras sin colision").toEqual([]);
    if (width === 1024) {
      expect(d!.tableScrollW, "tabla cabe en su region a 1024").toBeLessThanOrEqual(d!.regionClientW + 1);
      if (d!.status) expect(d!.status.clipped, "mensaje de estado visible").toBe(false);
    }
    if (width === 1024) {
      await page.addStyleTag({ content: "nextjs-portal{display:none!important}" });
      await page.screenshot({ path: "/tmp/shots/kt_after_1024.png", fullPage: true });
    }
  });
}
