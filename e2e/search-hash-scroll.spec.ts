import { expect, test, type Page } from '@playwright/test';
// Calentamiento del chunk de la paleta (patrón del repo, cf. 'MSFT ALERT'
// en search-hash-scroll.spec.ts): con el dev server frío (CI), el primer
// Ctrl+K compila el chunk del diálogo y los listeners de Escape de Radix se
// registran después de la primera pintada, perdiendo la tecla y dejando un
// diálogo abierto huérfano. Abrir y cerrar una vez estabiliza el entorno;
// las aserciones medidas después siguen siendo estrictas.
async function warmUpPalette(page: Page) {
    await page.keyboard.press('Control+k');
    await expect(page.locator('[role="dialog"]')).toHaveCount(1);
    for (let i = 0; i < 3 && (await page.locator('[role="dialog"]').count()) > 0; i++) {
        await page.keyboard.press('Escape');
        await page.waitForTimeout(300);
    }
    await expectNoDialogs(page);
}

// Diagnóstico: si queda algún role="dialog", el error dice cuál es (nombre,
// atributos y principio del texto) en vez de solo «recibido 1».
async function expectNoDialogs(page: Page) {
    try {
        await expect(page.locator('[role="dialog"]')).toHaveCount(0);
    } catch (error) {
        const found = await page.locator('[role="dialog"]').evaluateAll((nodes) => nodes.map((node) => ({
            label: node.getAttribute('aria-label') ?? node.getAttribute('aria-labelledby'),
            state: node.getAttribute('data-state'),
            id: node.id,
            inShadow: node.getRootNode() instanceof ShadowRoot,
            text: (node.textContent ?? '').trim().slice(0, 160),
        })));
        throw new Error(`Quedan diálogos abiertos: ${JSON.stringify(found)}\n${String(error)}`);
    }
}

// Bug (22-oct-2026, prod): comandos de ficha con ancla desde la paleta
// («MSFT GP») con la página YA abierta y desplazada abajo: location.hash
// quedaba fijado pero la vista no se movía al ancla (#grafico a -3155 px
// del viewport). El App Router no hace scroll al ancla en navegación a la
// misma ruta; la paleta desplaza ella (lib/search/scroll-to-hash).
// ALERT ya no es un ancla: su copy («Alertas») prometía la lista y llevaba
// solo al botón de crear; ahora apunta al gestor /alerts?symbol= (mismo
// deep-link que QuickAlertButton, diálogo pre-rellenado, sin creación hasta
// el envío explícito del usuario).
test.describe('paleta: comandos de ficha (ancla y destino)', () => {
    test.skip(process.env.E2E_UI_RUN !== '1', 'Necesita frontend E2E');
    test.setTimeout(90000);

    test('MSFT ALERT lleva al gestor /alerts con el símbolo pre-rellenado', async ({ page }) => {
        await page.setViewportSize({ width: 1280, height: 860 });
        await page.goto('/research/MSFT', { waitUntil: 'networkidle' });
        // Pre-compila /alerts en el dev server: la navegación solo compromete
        // la URL cuando llega el payload RSC, y una compilación fría de la
        // ruta superaría el timeout del expect de abajo.
        await page.request.get('/alerts');
        await page.keyboard.press('Control+k');
        const input = page.locator('[role="dialog"] input');
        await expect(input).toBeFocused();
        // El comando exacto se pinta sin depender de las populares: se puede
        // teclear antes de que resuelva la lista (no hace falta Finnhub).
        await input.fill('MSFT ALERT');
        // Esperar a que el comando exacto esté renderizado y seleccionado:
        // sin esto, Enter puede ganar la carrera al filtrado y elegir la
        // fila de la acción (navega a /research/MSFT en vez de /alerts).
        await expect(page.locator('[role="dialog"] [cmdk-item]').filter({ hasText: 'Alertas' }).first()).toBeVisible();
        await page.keyboard.press('Enter');

        await expect(page).toHaveURL(/\/alerts\?symbol=MSFT$/, { timeout: 20000 });
        // Deep-link convenido con QuickAlertButton: el diálogo de creación
        // abre con el símbolo pre-rellenado; NO se crea ninguna alerta hasta
        // el submit explícito del usuario.
        await expect(page.locator('#symbol')).toHaveValue('MSFT');
    });

    test('comando sin ancla sigue navegando (MSFT TESIS)', async ({ page }) => {
        await page.setViewportSize({ width: 1280, height: 860 });
        await page.goto('/research/MSFT', { waitUntil: 'networkidle' });
        await warmUpPalette(page);
        await page.keyboard.press('Control+k');
        const input = page.locator('[role="dialog"] input');
        await expect(input).toBeFocused();
        await expect(page.locator('[role="dialog"] [cmdk-item]').first()).toBeVisible();
        await input.fill('MSFT TESIS');
        await expect(page.locator('[role="dialog"] [cmdk-item]').filter({ hasText: 'Tesis' }).first()).toBeVisible();
        await page.keyboard.press('Enter');
        await expect(page).toHaveURL(/\/research\/MSFT\/tesis$/);
        await expectNoDialogs(page);
    });
});
