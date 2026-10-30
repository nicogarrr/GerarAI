import { expect, test } from '@playwright/test';
test.skip(process.env.E2E_EXTENDED_QUOTE_RUN !== '1', 'Run scripts/test-extended-quote.mjs');
const quote = {
    ticker: 'MSFT', status: 'available', session: 'post', price_session: 'post', price: 523.0,
    timestamp: 1791497100, trading_date: '2026-10-08', currency: 'USD', fetched_at: 1791497100,
    source: 'Yahoo Finance (no oficial), retraso posible', previous_close: 529.76,
    previous_close_timestamp: null, change: -6.76, change_percent: -1.276,
    regular_close: 522.61, regular_close_timestamp: 1791489601,
    open: 533.51, high: 533.51, low: 518.79, metrics_timestamp: 1791489540, metrics_session: '2026-10-08',
};
for (const width of [1440, 390]) {
    test(`quote with real schema, mock provider ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        let response: Record<string, unknown> = quote;
        let calls = 0;
        await page.route('**/api/companies/MSFT/extended-quote', route => {
            calls++;
            return route.fulfill({ json: response });
        });
        await page.clock.install();
        await page.goto('/extended-quote-preview');
        const header = page.getByTestId('company-header-quote');
        await expect(header.getByText('Post-cierre · 9 oct, 00:05 CEST', { exact: true })).toBeVisible();
        // Cabecera limpia (Nico, 30-oct-2026): la procedencia ya no se muestra.
        await expect(header.getByText('Yahoo Finance (no oficial), retraso posible · 00:05 (Madrid)', { exact: true })).toHaveCount(0);
        await expect(header.getByText('Cierre anterior', { exact: true }).locator('..').locator('dd')).toHaveText('N/D');
        await expect(header.getByText('Más detalle', { exact: true })).toHaveCount(0);
        await expect(header.getByText('Cierre regular:', { exact: false })).toHaveCount(0);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: `test-results/extended-quote-${width}.png`, fullPage: true });
        const initialCalls = calls;
        response = { ...quote, session: 'pre', price_session: 'pre', status: 'retrasado' };
        await page.clock.fastForward(300000);
        await expect(header.getByText('Premercado · 9 oct, 00:05 CEST · Retrasado', { exact: true })).toBeVisible();
        response = { ...quote, session: 'cerrado', change: null, change_percent: null };
        await page.clock.fastForward(300000);
        await expect(header.getByText('Último post-cierre · 9 oct, 00:05 CEST', { exact: true })).toBeVisible();
        await page.screenshot({ path: `test-results/extended-quote-closed-${width}.png`, fullPage: true });
        await expect(header.getByText('-1,28%', { exact: true })).not.toBeVisible();
        response = { status: 'unavailable' };
        await page.clock.fastForward(1800000);
        await expect(header.locator('.text-4xl')).toHaveText('N/D');
        expect(calls).toBe(initialCalls + 3);
        await page.screenshot({ path: `test-results/extended-quote-nd-${width}.png`, fullPage: true });
        const beforeHidden = calls;
        await page.evaluate(() => Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' }));
        await page.clock.fastForward(1800000);
        expect(calls).toBe(beforeHidden);
        response = { ...quote, timestamp: null };
        await page.evaluate(() => {
            Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
            document.dispatchEvent(new Event('visibilitychange'));
        });
        await expect.poll(() => calls).toBe(beforeHidden + 1);
        await expect(header.locator('.text-4xl')).toHaveText('N/D');
    });
}

test('real authenticated proxy serves the gated E2E fixture without Yahoo', async ({ page }) => {
    const responsePromise = page.waitForResponse('**/api/companies/MSFT/extended-quote');
    await page.goto('/extended-quote-preview');
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    expect(await response.json()).toMatchObject({ price: 336.56, source: 'Fixture local', timestamp: 1788966000 });
    const header = page.getByTestId('company-header-quote');
    await expect(header.getByText('336,56 US$', { exact: true })).toBeVisible();
    await expect(header.getByText('+2,34', { exact: false })).toBeVisible();
    await expect(header.getByText('Más detalle', { exact: true })).toHaveCount(0);
    await expect(header.getByText(/Sesión regular del/)).toHaveCount(0);
    await page.screenshot({ path: 'test-results/extended-quote-test-fixture.png', fullPage: true });
});

for (const width of [1440, 390]) {
    test(`missing SSR master identity still requests trusted listing recovery ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        let calls = 0;
        await page.route('**/api/companies/MSFT/extended-quote?resolveListing=1', route => {
            calls++;
            return route.fulfill({ json: quote });
        });
        await page.goto('/extended-quote-preview?missingIdentity=1');
        const header = page.getByTestId('company-header-quote');
        await expect(header.locator('.text-4xl')).toHaveText('523,00 US$');
        // En dev, React StrictMode monta el efecto dos veces y la primera lectura
        // se aborta; con reactStrictMode desactivado (como en producción) es 1.
        expect(calls).toBeGreaterThanOrEqual(1);
        expect(calls).toBeLessThanOrEqual(2);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: `test-results/quote-recovered-${width}.png`, fullPage: true });
    });
}
