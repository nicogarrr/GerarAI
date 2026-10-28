/**
 * Guard de bundle: las pestañas no iniciales de /portfolio y el formulario de
 * «Añadir inversión» cargan diferidos (next/dynamic), para que su JS no viaje
 * en el bundle inicial de la ruta. Si alguien vuelve a imports estáticos,
 * /portfolio recupera ~28 KB gz de JS inicial y este guard lo pilla.
 * Ejecución: node --experimental-strip-types --test scripts/portfolio-lazy-tabs-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const source = (relativePath: string): string => readFileSync(join(root, relativePath), 'utf8');

describe('portfolio: pestañas secundarias diferidas', () => {
    const tabs = source('components/portfolio/PortfolioTabs.tsx');

    it('las vistas no iniciales se importan con next/dynamic, no estático', () => {
        for (const view of ['PortfolioHoldings', 'PortfolioTransactions', 'PortfolioScores', 'SavingsProjection', 'PortfolioForecast', 'PortfolioDividends']) {
            assert.ok(
                tabs.includes(`dynamic(() => import('@/components/portfolio/${view}')`),
                `${view} debe cargar con dynamic()`,
            );
            assert.ok(
                !tabs.includes(`import ${view} from`),
                `${view} no debe tener import estático en PortfolioTabs`,
            );
        }
    });

    it('la pestaña inicial (resumen) se queda eager', () => {
        for (const eager of ['PortfolioSummary', 'PortfolioAllocation', 'PortfolioTearsheet']) {
            assert.ok(tabs.includes(`import ${eager} from`), `${eager} debe seguir con import estático`);
        }
    });

    it('las vistas diferidas muestran un fallback con role=status mientras llega el chunk', () => {
        assert.ok(tabs.includes('TabFallback'), 'debe existir un fallback de pestaña');
        assert.ok(tabs.includes('role="status"'), 'el fallback anuncia la carga a lectores de pantalla');
        assert.ok(tabs.includes('{ loading: TabFallback }'), 'todas las vistas diferidas usan el fallback');
    });
});

describe('portfolio: formulario de añadir inversión diferido', () => {
    const button = source('components/portfolio/AddTransactionButton.tsx');
    const dialog = source('components/portfolio/AddTransactionDialog.tsx');

    it('el diálogo con el formulario carga con dynamic() desde el botón', () => {
        assert.ok(button.includes("import('./AddTransactionDialog')"), 'el diálogo debe ser un import dinámico');
        assert.ok(!button.includes('TickerSearchInput'), 'el buscador de ticker vive en el diálogo, no en el botón');
    });

    it('el chunk se precarga al rozar el gatillo (pointerdown/focus)', () => {
        assert.ok(button.includes('onPointerDown'), 'precarga en pointerdown');
        assert.ok(button.includes('onFocus'), 'precarga en focus');
    });

    it('una vez abierto, el diálogo queda montado al cerrar (conserva lo escrito)', () => {
        assert.ok(button.includes('openedOnce'), 'el botón recuerda la primera apertura');
    });

    it('el diálogo contiene el formulario completo (buscador, validación, acción)', () => {
        assert.ok(dialog.includes('TickerSearchInput'), 'el buscador de ticker está en el diálogo');
        assert.ok(dialog.includes('addTransaction'), 'la server action se invoca desde el diálogo');
        assert.ok(dialog.includes('DialogContent'), 'el contenido Radix vive en el diálogo');
    });
});
