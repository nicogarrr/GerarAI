import { expect, test } from "@playwright/test";

test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1");
test.use({ viewport: { width: 768, height: 900 } });

// Regresión: a 768 px (md) la página /taxes hacía scroll horizontal de 9 px
// porque la tarjeta «Posiciones Fiscales» (min-content 513 px) inflaba la vía
// implícita de la grid de una columna y desbordaba el MAIN de 480 px.
test("taxes md768: sin scroll horizontal de página", async ({ page }) => {
  await page.goto("/taxes", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(4000);
  await page.addStyleTag({ content: "nextjs-portal{display:none!important}" });
  await expect(page.locator("main")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Posiciones Fiscales", exact: true })).toBeVisible();
  const m = await page.evaluate(() => {
    const el = document.scrollingElement ?? document.documentElement;
    const main = document.querySelector("main");
    const grid = document.querySelector("main div.grid");
    const mainR = main?.getBoundingClientRect();
    const cards = grid
      ? Array.from(grid.children).map((c) => Math.round(c.getBoundingClientRect().right))
      : [];
    return {
      scrollW: el.scrollWidth,
      clientW: el.clientWidth,
      mainRight: mainR ? Math.round(mainR.right) : null,
      cards,
    };
  });
  console.log("TAXES_MD=" + JSON.stringify(m));
  expect(m.scrollW).toBeLessThanOrEqual(m.clientW);
  expect(m.mainRight).not.toBeNull();
  expect(m.cards.length).toBeGreaterThan(0);
  if (m.mainRight !== null) {
    for (const right of m.cards) {
      expect(right).toBeLessThanOrEqual(m.mainRight);
    }
  }
});
