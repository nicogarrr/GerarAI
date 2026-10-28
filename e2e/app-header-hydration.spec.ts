import { expect, test, type Page } from '@playwright/test';

async function fits(page: Page) {
  const header = page.locator('.header');
  await expect(header).toBeVisible();
  const geometry = await header.evaluate((element) => {
    const bounds = element.getBoundingClientRect();
    const controls = [...element.querySelectorAll('button, a')]
      .filter((item) => item.getClientRects().length && getComputedStyle(item).visibility !== 'hidden')
      .map((item) => item.getBoundingClientRect());
    return {
      height: bounds.height,
      fits: controls.every((box) => box.left >= 0 && box.right <= innerWidth),
      overflow: document.documentElement.scrollWidth > innerWidth,
    };
  });
  expect(geometry).toEqual({ height: 56, fits: true, overflow: false });
}

test.describe('header app antes y después de hidratar', () => {
  test.setTimeout(90000);
  test.skip(process.env.E2E_UI_RUN !== '1', 'Necesita frontend E2E');
  for (const width of [320, 360, 390]) {
    test(`SSR sin JavaScript cabe a ${width}px`, async ({ browser }) => {
      const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width, height: 900 } });
      const page = await context.newPage();
      await page.goto('/security', { waitUntil: 'domcontentloaded' });
      await fits(page);
      await context.close();
    });
    test(`JavaScript demorado e hidratado cabe a ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      let release!: () => void;
      const gate = new Promise<void>((resolve) => { release = resolve; });
      await page.route('**/*', async (route) => {
        if (route.request().resourceType() === 'script') await gate;
        await route.continue();
      });
      try {
        await page.goto('/security', { waitUntil: 'commit' });
        await fits(page);
      } finally {
        release();
      }
      const search = page.locator('.header [data-testid=\'search-command-trigger\']:visible').first();
      await expect(search).toBeVisible();
      await fits(page);
      await search.click();
      await expect(page.getByRole('dialog', { name: 'Buscar acciones', exact: true })).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(page.getByRole('dialog', { name: 'Buscar acciones', exact: true })).toHaveCount(0);
    });
  }
});
