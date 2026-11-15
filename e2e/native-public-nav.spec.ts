import { expect, test } from '@playwright/test';
import { waitForHydration } from './fixtures/wait-for-hydration';

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
for (const reducedMotion of ['no-preference', 'reduce'] as const) {
    test.describe(`native public nav (${reducedMotion})`, () => {
        test.skip(process.env.E2E_UI_RUN !== '1', 'Set E2E_UI_RUN=1 to run browser tests.');
        test.use({ reducedMotion });
        test('native modal, background focus, Escape, backdrop, links and resize', async ({ page }, testInfo) => {
            await page.goto('/metodologia');
            await waitForHydration(page);
            const trigger = page.getByRole('button', { name: 'Abrir menú de páginas', exact: true });
            const drawer = page.locator('dialog#public-mobile-nav-drawer');
            await trigger.click();
            await expect(drawer).toBeVisible();
            expect(await drawer.evaluate(d => d.matches(':modal'))).toBe(true);
            await expect(trigger).toHaveAttribute('aria-expanded', 'true');
            const close = drawer.getByRole('button', { name: 'Cerrar menú de páginas', exact: true });
            await expect(close).toBeFocused();
            await trigger.evaluate(e => e.focus());
            await expect(close).toBeFocused();
            await testInfo.attach('native-public-nav-390', { body: await page.screenshot(), contentType: 'image/png' });
            await page.keyboard.press('Escape');
            await expect(drawer).toHaveCount(0);
            await expect(trigger).toHaveAttribute('aria-expanded', 'false');
            await expect(trigger).toBeFocused();
            await trigger.click();
            await expect(drawer).toBeVisible();
            await page.mouse.click(30, 420);
            await expect(drawer).toHaveCount(0);
            await trigger.click();
            await drawer.getByRole('link', { name: 'Ayuda', exact: true }).click();
            await expect(page).toHaveURL(/\/help(?:[?#]|$)/);
            await expect(drawer).toHaveCount(0);
            await trigger.click();
            await expect(drawer).toBeVisible();
            await page.setViewportSize({ width: 1024, height: 844 });
            await expect(drawer).toHaveCount(0);
            expect(await page.locator('dialog:modal').count()).toBe(0);
        });
    });
}
