import { expect, test } from '@playwright/test';
test.skip(process.env.E2E_CHART_RUN !== '1', 'Isolated chart fixture, run with scripts/test-technical-chart.mjs');
for (const viewport of [{ width: 1440, height: 1080 }, { width: 390, height: 844 }, { width: 768, height: 1024 }]) {
    test(`price chart and technical reading ${viewport.width}px`, async ({ page }) => {
        await page.setViewportSize(viewport);
        const errors: string[] = [];
        page.on('pageerror', (error) => errors.push(error.message));
        await page.goto('/chart-preview');
        await expect(page.getByTestId('technical-price-canvas').locator('canvas').first()).toBeVisible();
        // Por debajo de md la lectura técnica va plegada: se abre antes de comprobarla.
        if (viewport.width < 768) await page.getByRole('button', { name: 'Lectura técnica', exact: true }).click();
        else await expect(page.getByRole('heading', { name: 'Lectura técnica', exact: true })).toBeVisible();
        // #2999: los pivotes viven solo en el gráfico, sin bloque escrito.
        await expect(page.getByText('Pivotes de referencia de la última vela', { exact: false })).toHaveCount(0);
        await expect(page.getByText('El proveedor no confirma el cierre de la última vela:', { exact: false })).toBeVisible();
        await expect(page.getByText('Último precio diario', { exact: false })).toBeVisible();
        await expect(page.getByText('Cierres diarios hasta', { exact: false })).toHaveCount(0);
        await expect(page.getByText('Niveles de retroceso (1M)')).toBeVisible();
        await expect(page.getByRole('tab')).toHaveCount(0);
        await page.getByRole('button', { name: '6M', exact: true }).click();
        await expect(page.getByRole('button', { name: '6M', exact: true })).toHaveAttribute('aria-pressed', 'true');
        const chart = await page.getByTestId('technical-price-canvas').boundingBox();
        const reading = await page.getByTestId('technical-reading').boundingBox();
        expect(chart).not.toBeNull(); expect(reading).not.toBeNull();
        if (viewport.width < 1280) expect(reading!.y).toBeGreaterThan(chart!.y + chart!.height);
        else expect(reading!.x).toBeGreaterThan(chart!.x + chart!.width);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        expect(errors).toEqual([]);
        await page.screenshot({ path: `test-results/technical-${viewport.width}.png`, fullPage: true });
    });
}
test('all reference ranges load without claiming daily points are intraday', async ({ page }) => {
    await page.goto('/chart-preview');
    for (const range of ['1D', '5D', '5A', 'Máx']) {
        await page.getByRole('button', { name: range, exact: true }).click();
        await expect(page.getByText(`Cargando rango ${range}`, { exact: true })).not.toBeVisible();
        await expect(page.getByTestId('technical-price-canvas').locator('canvas').first()).toBeVisible();
        await expect(page.getByRole('button', { name: range, exact: true })).toHaveAttribute('aria-pressed', 'true');
        if (range === '1D' || range === '5D') await expect(page.getByText('Horario (UTC) · Fixture local', { exact: false })).toBeVisible();
        if (range === 'Máx') await expect(page.getByText('Máximo disponible del proveedor', { exact: false })).toBeVisible();
    }
});
test('close-only history stays honest; missing history stays empty', async ({ page }) => {
    await page.goto('/chart-preview?mode=close');
    await expect(page.getByTestId('technical-price-canvas').locator('canvas').first()).toBeVisible();
    // #2999 quitó el bloque escrito de pivotes («Sin datos OHLC para calcular
    // niveles.»): con solo cierres, la lectura técnica se abstiene así.
    await expect(page.getByText('Estructura: sin datos OHLC suficientes.')).toBeVisible();
    await expect(page.getByText('Sin datos OHLC para Fibonacci.')).toBeVisible();
    await expect(page.getByText('OHLC completo necesario')).toBeVisible();
    await page.goto('/chart-preview?mode=empty');
    await expect(page.getByText('Sin datos suficientes para este rango')).toBeVisible();
});

test('no quote AND no history preserves an explicit unavailable workspace', async ({ page }) => {
    // La cabecera ya no lee snapshot.quote: pide su propia cotización a
    // /extended-quote (que en e2e devuelve el fixture 336,56 US$). «Sin
    // cotización» se simula en esa fuente.
    await page.route('**/api/companies/*/extended-quote*', (route) =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'unavailable' }) }));
    await page.goto('/chart-preview?mode=unavailable');
    await expect(page.getByTestId('company-header-quote')).toBeVisible();
    await expect(page.getByTestId('company-technical-chart')).toBeVisible();
    await expect(page.getByText('Sin datos suficientes para este rango')).toBeVisible();
    await expect(page.getByText('336,56 US$')).not.toBeVisible();
    await expect(page.getByText('Sin datos OHLC para Fibonacci.')).toBeVisible();
    await page.screenshot({ path: 'test-results/chart-unavailable.png', fullPage: true });
});

test('Yahoo close-only through real adapter and normalizer abstains in UI', async ({ page }) => {
    await page.goto('/chart-preview?mode=yahoo');
    await expect(page.getByTestId('technical-price-canvas').locator('canvas').first()).toBeVisible();
    await expect(page.getByText('Estructura: sin datos OHLC suficientes.')).toBeVisible();
    await expect(page.getByText('Sin datos OHLC para Fibonacci.')).toBeVisible();
    await expect(page.getByText('OHLC completo necesario')).toBeVisible();
    await page.screenshot({path:'test-results/yahoo-close-only-real-boundary.png',fullPage:true});
});
