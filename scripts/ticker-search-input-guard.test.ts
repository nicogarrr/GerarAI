/**
 * Buscador de ticker con autocompletado, unico para toda la app (Nico,
 * 20-oct-2026: Form 4 no sugeria «AMZN» al escribir «AMZ»). Una sola
 * implementacion inline sobre la busqueda del buscador global.
 * Ejecución: node --experimental-strip-types --test scripts/ticker-search-input-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const component = readFileSync('components/search/TickerSearchInput.tsx', 'utf8');

describe('buscador de ticker unificado (autocompletado inline)', () => {
    it('AMZ recupera la línea US por nombre verificado, no mediante alias inventado', () => {
        const action = readFileSync('lib/actions/finnhub.actions.ts', 'utf8');
        assert.ok(action.includes('encodeURIComponent(listing.description)'));
        assert.ok(action.includes('foldName(r.description) === foldName(listing.description)'));
        assert.ok(action.includes('r.symbol.toUpperCase().startsWith(prefix)'));
    });
    // Debounce de 300 ms, gate F215 (respuestas tardías), error de proveedor ≠
    // «sin resultados», Enter/flechas/Escape y «elegir no reabre la lista» se
    // comprueban usando el componente: tests/unit/components/TickerSearchInput.test.tsx.
    it('reutiliza la búsqueda del buscador global, con deadline', () => {
        assert.ok(component.includes('searchStocksWithStatus'), 'misma acción que SearchCommand/WatchlistAddButton');
        assert.ok(component.includes('withFetchDeadline'), 'deadline de 6 s (patrón watchlist)');
        assert.ok(component.includes('6000'), 'deadline de 6 s');
    });
    it('móvil primero: dropdown superpuesto (no empuja ni rompe el scroll) y objetivos táctiles', () => {
        assert.ok(component.includes('PopoverContent'), 'portal existente evita el recorte en diálogos');
        assert.ok(component.includes('--radix-popover-content-available-height'), 'altura se adapta al espacio disponible');
        assert.ok(component.includes('overflow-auto'), 'scroll interno de la lista');
        assert.ok(component.includes('min-h-11'), 'objetivos táctiles >=44px');
        assert.ok(component.includes('gate.invalidate()'), 'el desmontaje invalida respuestas tardías');
        assert.ok(component.includes('autoComplete="off"'), 'sin autocompletado nativo peleando con el de la app');
    });
    it('los consumidores lo usan (insider, alertas, cartera) sin inputs de ticker planos duplicados', () => {
        const insider = readFileSync('components/insider/InsiderSignalsView.tsx', 'utf8');
        const alerts = readFileSync('components/alerts/AlertsManager.tsx', 'utf8');
        const cartera = readFileSync('components/portfolio/AddTransactionButton.tsx', 'utf8') + readFileSync('components/portfolio/AddTransactionDialog.tsx', 'utf8');
        assert.ok(insider.includes("from '@/components/search/TickerSearchInput'"), 'Form 4 lo usa');
        assert.ok(alerts.includes("from '@/components/search/TickerSearchInput'"), 'crear alerta lo usa');
        assert.ok(cartera.includes("from '@/components/search/TickerSearchInput'"), 'añadir inversión lo usa');
        for (const path of ['app/(root)/search/page.tsx', 'app/(root)/knowledge-graph/page.tsx', 'app/(root)/portfolio/stress/page.tsx', 'app/(root)/research/page.tsx', 'app/(root)/research/sources/page.tsx', 'components/brain/GlobalBrainPanel.tsx', 'components/plan/PlanSetupDialog.tsx', 'components/work-products/WorkProductButton.tsx', 'components/watchlist/WatchlistAddButton.tsx', 'components/portfolio/EditTransactionDialog.tsx']) {
            assert.ok(readFileSync(path, 'utf8').includes('TickerSearchInput'), path);
        }
        assert.ok(!insider.includes("import { Input } from '@/components/ui/input'"), 'Form 4 ya no usa el input plano');
    });
});
