import { expect, test } from "@playwright/test";

const runUiE2E = process.env.E2E_UI_RUN === "1";
// Skip before the page fixture launches: the API-only job has no browser.
test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

// Verifica geometría real del carril a 390px y navegación por toque.
test("pestañas ficha 390px: carril deslizable con affordance visible y toque navega", async ({ page }) => {
  await page.goto("/research/UBER");
  const nav = page.getByTestId("company-navigation");
  await expect(nav).toBeVisible();

  // El carril desborda en 390px (6 pestañas) y muestra el affordance fino de
  // scroll-affordance-x (contrato visual de #5783), no scrollbar-hide.
  const metrics = await nav.evaluate((el) => ({
    overflowX: getComputedStyle(el).overflowX,
    scrollbarWidth: getComputedStyle(el).scrollbarWidth,
    desborda: el.scrollWidth > el.clientWidth,
  }));
  expect(metrics.overflowX).toBe("auto");
  expect(metrics.scrollbarWidth).toBe("thin");
  expect(metrics.desborda).toBe(true);

  // Check the center of each visible intersection, not a clipped link midpoint.
  const covered = await nav.evaluate((el) => {
    const bad: string[] = [];
    const rail = el.getBoundingClientRect();
    for (const a of Array.from(el.querySelectorAll("a"))) {
      const r = a.getBoundingClientRect();
      const left = Math.max(r.left, rail.left, 0);
      const right = Math.min(r.right, rail.right, window.innerWidth);
      const top = Math.max(r.top, rail.top, 0);
      const bottom = Math.min(r.bottom, rail.bottom, window.innerHeight);
      if (right <= left || bottom <= top) continue;
      const hit = document.elementFromPoint((left + right) / 2, (top + bottom) / 2);
      if (!(hit === a || a.contains(hit))) bad.push(a.textContent ?? "?");
    }
    return bad;
  });
  expect(covered).toEqual([]);

  // Tocar una pestaña navega a su vista y la activa queda visible entera.
  await nav.getByRole("link", { name: "Tesis" }).tap();
  await expect(page).toHaveURL(/view=tesis/);
  const tesis = nav.getByRole("link", { name: "Tesis" });
  await expect(tesis).toHaveAttribute("aria-current", "page");
  const box = await tesis.boundingBox();
  const navBox = await nav.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(navBox!.x - 1);
  expect(box!.x + box!.width).toBeLessThanOrEqual(navBox!.x + navBox!.width + 1);
  await page.screenshot({ path: "test-results/ficha-tabs-390px.png" });
});
