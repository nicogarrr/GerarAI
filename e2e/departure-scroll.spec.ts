import { expect, test } from '@playwright/test';
import { armDepartureScroll } from './fixtures/departure-scroll';

// Same lane gate as the other browser specs: API CI has no Chromium.
test.skip(process.env.E2E_UI_RUN !== '1', 'Set E2E_UI_RUN=1 to run browser tests.');

// Standalone real-browser oracle regression: no backend, credentials or vendors.
test('departure oracle sees anchored growth between an early sample and the click', async ({ page }) => {
    await page.route('http://scroll.test/**', route => route.fulfill({
        contentType: 'text/html',
        body: '<div id="quote" style="height:100px"></div><div style="height:1000px"></div><a href="#report">Informe</a><div style="height:3000px"></div>',
    }));
    await page.goto('http://scroll.test/');
    await page.evaluate(() => window.scrollTo(0, 900));
    const early = await page.evaluate(() => Math.round(window.scrollY));
    const link = page.getByRole('link', { name: 'Informe' });
    const readDeparture = await armDepartureScroll(page, link);
    await page.evaluate(() => { document.getElementById('quote')!.style.height = '132px'; });
    await expect.poll(() => page.evaluate(() => Math.round(window.scrollY))).toBe(early + 32);
    await link.click();
    expect(await readDeparture()).toBe(early + 32);
});
