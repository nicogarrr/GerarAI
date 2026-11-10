import { expect, test } from '@playwright/test';

// Deterministic hydration regression: hold the application scripts, click the
// real server HTML, then release the scripts. No timeout increase or sleep can
// substitute for the lost intent. The inline, nonce-bearing capture must work
// before React (and before GlobalBrain's listener) exists.
test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
test.describe('mobile clicks in the initial HTML', () => {
    test.skip(process.env.E2E_UI_RUN !== '1', 'Set E2E_UI_RUN=1 to run browser tests.');
    for (const c of [
        { locale: 'es', kind: 'mobile-nav', title: 'Menú de navegación', key: 'gerarai:open-nav:pending' },
        { locale: 'es', kind: 'brain', title: 'Cerebro GerarAI', key: 'gerarai:open-brain:pending' },
        { locale: 'en', kind: 'brain', title: 'GerarAI Brain', key: 'gerarai:open-brain:pending' },
    ]) {
        test(`${c.locale} ${c.kind}: one click before hydration opens after hydration`, async ({ page, context, baseURL }, testInfo) => {
            await context.addCookies([{ name: 'gerarai_locale', value: c.locale, url: baseURL ?? 'http://localhost:3000' }]);
            let release!: () => void;
            const gate = new Promise<void>((resolve) => { release = resolve; });
            await page.route('**/_next/**/*.js*', async (route) => { await gate; await route.continue(); });
            try {
                await page.goto('/inicio', { waitUntil: 'commit' });
                const trigger = page.locator(`[data-early-open="${c.kind}"]`);
                await expect(trigger).toBeVisible();
                await expect(trigger).not.toHaveAttribute('data-hydrated', '1');
                await expect(page.locator('html')).not.toHaveAttribute('data-brain-ready', '1');
                await trigger.click();
                expect(await page.evaluate((key) => sessionStorage.getItem(key), c.key)).not.toBeNull();
                release();
                const dialog = page.getByRole('dialog', { name: c.title, exact: true });
                await expect(dialog).toBeVisible();
                expect(await page.evaluate((key) => sessionStorage.getItem(key), c.key)).toBeNull();
                await testInfo.attach('opened-at-390', { body: await page.screenshot(), contentType: 'image/png' });
                await page.keyboard.press('Escape');
                await expect(dialog).not.toBeVisible();
                // Closing must not leave another pending opening for navigation.
                expect(await page.evaluate((key) => sessionStorage.getItem(key), c.key)).toBeNull();
            } finally {
                release();
                await page.unrouteAll({ behavior: 'ignoreErrors' });
            }
        });
    }
});
