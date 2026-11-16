import { expect, test } from "@playwright/test";

const runUiE2E = process.env.E2E_UI_RUN === "1";
// Skip before the page fixture launches: the API-only job has no browser.
test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

// Verifica geometría real del carril a 390px y navegación por toque.
test("pestañas ficha 390px: carril deslizable sin barra visible y toque navega", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/research/UBER");
  const nav = page.getByTestId("company-navigation");
  await expect(nav).toBeVisible();

  // El carril desborda en 390px (6 pestañas) pero la barra queda oculta.
  const metrics = await nav.evaluate((el) => ({
    overflowX: getComputedStyle(el).overflowX,
    scrollbarWidth: getComputedStyle(el).scrollbarWidth,
    desborda: el.scrollWidth > el.clientWidth,
  }));
  expect(metrics.overflowX).toBe("auto");
  expect(metrics.scrollbarWidth).toBe("none");
  expect(metrics.desborda).toBe(true);

  // Nada tapa los toques: el centro de cada pestaña visible resuelve a ella.
  const covered = await nav.evaluate((el) => {
    const bad: string[] = [];
    for (const a of Array.from(el.querySelectorAll("a"))) {
      const r = a.getBoundingClientRect();
      if (r.right < 0 || r.left > window.innerWidth) continue;
      const cx = Math.min(Math.max(r.left + r.width / 2, 2), window.innerWidth - 2);
      const hit = document.elementFromPoint(cx, r.top + r.height / 2);
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
