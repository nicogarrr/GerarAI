import { expect, test } from '@playwright/test';

// Bug (22-oct-2026, prod): comandos de ficha con ancla desde la paleta
// («MSFT GP», «MSFT ALERT») con la página YA abierta y desplazada abajo:
// location.hash quedaba fijado pero la vista no se movía al ancla
// (#grafico a -3155 px del viewport). El App Router no hace scroll al ancla
// en navegación a la misma ruta; la paleta desplaza ella (lib/search/scroll-to-hash).
test.describe('paleta: comandos con ancla desplazan la vista', () => {
    test.skip(process.env.E2E_UI_RUN !== '1', 'Necesita frontend E2E');
    test.setTimeout(90000);

    test('MSFT ALERT con la ficha abierta abajo: la vista llega a #alerta', async ({ page }) => {
        await page.setViewportSize({ width: 1280, height: 860 });
        await page.goto('/research/MSFT', { waitUntil: 'networkidle' });
        await page.locator('#alerta').waitFor();
        // Espaciador sintético sobre el ancla: sin fix, el scroll al TOPE del
        // dev server dejaría el ancla a >3000 px (en prod quedaba a -3259 px);
        // con el fix debe quedar pegada arraiba igualmente. Hace la prueba
        // determinista en ambos entornos.
        await page.evaluate(() => {
            const spacer = document.createElement('div');
            spacer.style.height = '3000px';
            spacer.setAttribute('data-e2e-spacer', '');
            document.getElementById('alerta')!.before(spacer);
        });
        await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
        const before = await page.evaluate(() => window.scrollY);
        expect(before).toBeGreaterThan(500);

        await page.keyboard.press('Control+k');
        const input = page.locator('[role="dialog"] input');
        await expect(input).toBeFocused();
        // Dejar que la carga inicial (populares) RESUELVA antes de teclear:
        // si resuelve después del fill, su setSelectedValue(stock:...) pisa
        // la selección del comando exacto y Enter navega a la acción sin hash.
        await expect(page.locator('[role="dialog"] [cmdk-item]').first()).toBeVisible();
        await input.fill('MSFT ALERT');
        // Esperar a que el comando exacto esté renderizado y seleccionado:
        // sin esto, Enter puede ganar la carrera al filtrado y elegir la
        // fila de la acción (navega a /research/MSFT sin hash).
        await expect(page.locator('[role="dialog"] [cmdk-item]').filter({ hasText: 'Alertas' }).first()).toBeVisible();
        await page.keyboard.press('Enter');

        await expect(page).toHaveURL(/\/research\/MSFT#alerta$/);
        // El ancla debe quedar pegada ARRIBA del viewport (scroll-mt-6 = 24 px,
        // con margen por layout shift de Suspense resolviendo tras el scroll):
        // sin el fix, prod la dejaba a -3200 px y el scroll local a top=254
        // (scroll al tope, no al ancla); en ambos casos este rango falla.
        await expect(async () => {
            const top = await page.evaluate(() => document.getElementById('alerta')!.getBoundingClientRect().top);
            expect(top).toBeGreaterThanOrEqual(0);
            expect(top).toBeLessThan(120);
        }).toPass({ timeout: 8000 });
    });

    test('comando sin ancla sigue navegando (MSFT TESIS)', async ({ page }) => {
        await page.setViewportSize({ width: 1280, height: 860 });
        await page.goto('/research/MSFT', { waitUntil: 'networkidle' });
        await page.keyboard.press('Control+k');
        const input = page.locator('[role="dialog"] input');
        await expect(input).toBeFocused();
        await expect(page.locator('[role="dialog"] [cmdk-item]').first()).toBeVisible();
        await input.fill('MSFT TESIS');
        await expect(page.locator('[role="dialog"] [cmdk-item]').filter({ hasText: 'Tesis' }).first()).toBeVisible();
        await page.keyboard.press('Enter');
        await expect(page).toHaveURL(/\/research\/MSFT\/tesis$/);
        await expect(page.locator('[role="dialog"]')).toHaveCount(0);
    });
});
