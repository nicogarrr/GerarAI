import { expect, test } from '@playwright/test';
import { waitForHydration } from './fixtures/wait-for-hydration';

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
for (const reducedMotion of ['no-preference', 'reduce'] as const) {
    test.describe(`native brain (${reducedMotion})`, () => {
        test.skip(process.env.E2E_UI_RUN !== '1', 'Set E2E_UI_RUN=1 to run browser tests.');
        test.use({ reducedMotion });
        test('modal focus, draft-only use, maximize and Escape return', async ({ page }, testInfo) => {
            await page.goto('/alerts');
            await waitForHydration(page);
            const trigger = page.getByRole('button', { name: 'Abrir el cerebro', exact: true }).first();
            await trigger.click();
            const panel = page.getByRole('dialog', { name: 'Cerebro GerarAI', exact: true });
            await expect(panel).toBeVisible();
            expect(await panel.evaluate(d => d.matches('dialog:modal'))).toBe(true);
            const input = panel.getByRole('textbox', { name: 'Pregunta al cerebro' });
            await expect(input).toBeFocused();
            await trigger.evaluate(e => e.focus());
            await expect(input).toBeFocused();
            await panel.getByRole('button', { name: 'Abrir la guía de investigación por empresa' }).click();
            const ticker = panel.getByRole('combobox', { name: 'Ticker de la guía de investigación', exact: true });
            await expect(ticker).toBeVisible();
            await expect(ticker).toHaveAttribute('placeholder', 'Ticker');
            await expect(ticker).toHaveAttribute('aria-label', 'Ticker de la guía de investigación');
            expect((await ticker.boundingBox())!.width).toBeGreaterThanOrEqual(72);
            await input.fill('Borrador de prueba, sin enviar');
            await panel.getByRole('button', { name: 'Maximizar el cerebro' }).click();
            await expect.poll(async () => Math.round((await panel.boundingBox())!.x)).toBe(16);
            await panel.getByRole('button', { name: 'Restaurar el cerebro' }).click();
            await expect(input).toHaveValue('Borrador de prueba, sin enviar');
            await testInfo.attach('native-brain-390', { body: await page.screenshot(), contentType: 'image/png' });
            await page.keyboard.press('Escape');
            await expect(panel).toHaveCount(0);
            await expect(trigger).toBeFocused();
        });
    });
}
