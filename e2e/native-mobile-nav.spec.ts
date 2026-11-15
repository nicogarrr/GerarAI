import { expect, test } from '@playwright/test';
import { waitForHydration } from './fixtures/wait-for-hydration';

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
for (const reducedMotion of ['no-preference', 'reduce'] as const) {
    test.describe(`native mobile nav (${reducedMotion})`, () => {
        test.skip(process.env.E2E_UI_RUN !== '1', 'Set E2E_UI_RUN=1 to run browser tests.');
        test.use({ reducedMotion });
        test('inert background, nested search, Escape order, focus return and resize', async ({ page }, testInfo) => {
            await page.goto('/alerts');
            await waitForHydration(page);
            const trigger = page.getByRole('button', { name: 'Abrir menú de navegación', exact: true });
            await trigger.click();
            const drawer = page.locator('dialog#mobile-nav-drawer');
            await expect(drawer).toBeVisible();
            expect(await drawer.evaluate(d => d.matches(':modal'))).toBe(true);
            await expect(drawer).not.toHaveAttribute('aria-modal');
            const close = drawer.getByRole('button', { name: 'Cerrar menú de navegación', exact: true });
            await expect(close).toBeFocused();
            await trigger.evaluate(e => e.focus());
            await expect(close).toBeFocused(); // Native modal blocks background focus.
            await testInfo.attach('native-drawer-390', { body: await page.screenshot(), contentType: 'image/png' });
            await drawer.getByTestId('search-command-trigger').click();
            const search = drawer.locator('[data-slot="dialog-content"]');
            await expect(search).toBeVisible();
            await search.getByRole('combobox').fill('AAPL');
            await expect(search.getByRole('combobox')).toHaveValue('AAPL');
            await page.keyboard.press('Escape');
            await expect(search).not.toBeVisible();
            await expect(drawer).toBeVisible();
            await expect(drawer.getByTestId('search-command-trigger')).toBeFocused();
            await page.keyboard.press('Escape');
            await expect(drawer).toHaveCount(0);
            await expect(trigger).toBeFocused();
            await trigger.click();
            await expect(drawer).toBeVisible();
            await page.mouse.click(375, 420); // Outside the 320px-wide panel.
            await expect(drawer).toHaveCount(0);
            await trigger.click();
            await expect(drawer).toBeVisible();
            await page.setViewportSize({ width: 1024, height: 844 });
            await expect(drawer).toHaveCount(0);
            expect(await page.locator('dialog:modal').count()).toBe(0);
        });
    });
}
