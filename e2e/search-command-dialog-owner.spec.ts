import { expect, test } from '@playwright/test';

// Owner único del buscador global: antes Ctrl+K abría un CommandDialog por
// instancia montada (desktop + icono móvil), apilados píxel a píxel. Estas
// pruebas fijan el contrato DOM: 1 diálogo, 1 alert, foco devuelto al
// gatillo, Escape cierra, reintento limpia el error.
test.describe('buscador global: una sola instancia de diálogo', () => {
    test.skip(process.env.E2E_UI_RUN !== '1', 'Necesita frontend E2E');
    test.setTimeout(90000);

    for (const width of [1280, 390]) {
        test(`Ctrl+K abre exactamente 1 diálogo a ${width}px y Escape devuelve el foco`, async ({ page }) => {
            await page.setViewportSize({ width, height: 860 });
            await page.goto('/research/MSFT', { waitUntil: 'networkidle' });
            await page.locator('[data-testid="search-command-trigger"]:visible').first().waitFor();
            await page.waitForTimeout(500); // registro de instancias tras hidratar

            await page.keyboard.press('Control+k');
            await expect(page.locator('[role="dialog"]')).toHaveCount(1);

            // El foco entra en el diálogo (input de búsqueda)
            await expect(page.locator('[role="dialog"] input')).toBeFocused();

            await page.keyboard.press('Escape');
            await expect(page.locator('[role="dialog"]')).toHaveCount(0);
            const focusBack = await page.evaluate(() =>
                document.activeElement instanceof HTMLElement
                && document.activeElement.getAttribute('data-testid') === 'search-command-trigger');
            expect(focusBack).toBe(true);
        });
    }

    test('fallo inyectado: 1 solo alert, sin toast, y el reintento lo limpia', async ({ page }) => {
        await page.setViewportSize({ width: 1280, height: 860 });
        await page.route('**/*', (route) => {
            const req = route.request();
            if (req.method() === 'POST' && req.headers()['next-action']) {
                return route.fulfill({ status: 500, contentType: 'text/plain', body: 'injected failure' });
            }
            return route.continue();
        });
        await page.goto('/research/MSFT', { waitUntil: 'networkidle' });
        await page.locator('[data-testid="search-command-trigger"]:visible').first().waitFor();
        await page.waitForTimeout(500);

        await page.keyboard.press('Control+k');
        await expect(page.locator('[role="dialog"]')).toHaveCount(1);
        // Fallo de populares al abrir: un único alert inline, cero toasts
        await expect(page.locator('[role="dialog"] [role="alert"]')).toHaveCount(1, { timeout: 15000 });
        await expect(page.locator('[data-sonner-toast]')).toHaveCount(0);

        // Fallo de búsqueda: sigue siendo 1 solo alert, sin toast apilado
        await page.keyboard.type('ASTS');
        await page.waitForTimeout(1800); // debounce 300ms + red
        await expect(page.locator('[role="dialog"] [role="alert"]')).toHaveCount(1);
        await expect(page.locator('[data-sonner-toast]')).toHaveCount(0);

        // Reintento con el fallo retirado: el alert desaparece
        await page.unroute('**/*');
        await page.keyboard.press('Control+a');
        await page.keyboard.type('AST');
        await expect(page.locator('[role="dialog"] [role="alert"]')).toHaveCount(0, { timeout: 15000 });
    });
});

test.describe('owner huérfano (objeción auditor)', () => {
    test.skip(process.env.E2E_UI_RUN !== '1', 'Necesita frontend E2E');
    test.setTimeout(90000);

    test('desmontar a la dueña (drawer -> resize) no deja diálogo fantasma', async ({ page }) => {
        await page.setViewportSize({ width: 390, height: 860 });
        await page.goto('/research/MSFT', { waitUntil: 'networkidle' });
        await page.locator('[data-testid="search-command-trigger"]:visible').first().waitFor();
        await page.waitForTimeout(500);

        // Drawer móvil: su SearchCommand es una instancia más.
        await page.click('button[aria-label="Abrir menú de navegación"]');
        await expect(page.locator('[role="dialog"]')).toHaveCount(1); // el drawer
        await page.locator('[role="dialog"] [data-testid="search-command-trigger"]').click();
        await expect(page.locator('[role="dialog"]')).toHaveCount(2); // drawer + paleta (dueña: drawer)

        // Cruzar el breakpoint desmonta el drawer (y a la dueña) con la paleta abierta.
        await page.setViewportSize({ width: 1280, height: 860 });
        await expect(page.locator('[role="dialog"]')).toHaveCount(0);

        // El store no puede quedar open=true huérfano: Ctrl+K ABRE (no cierra fantasma).
        await page.keyboard.press('Control+k');
        await expect(page.locator('[role="dialog"]')).toHaveCount(1);
        await expect(page.locator('[role="dialog"] input')).toBeFocused();
    });
});
