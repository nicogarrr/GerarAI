/**
 * Guard de primer pintado de /portfolio: la página solo espera la lectura
 * esencial (summary) antes de devolver JSX; las lecturas tolerantes viajan
 * como promesas y cada panel las desenvuelve con use() dentro de su propio
 * <Suspense> con reserva de espacio. Si alguien vuelve a `await Promise.all`,
 * la página entera queda bloqueada por el módulo más lento (medido en prod
 * 17-nov-2026: TTFB 0,3 s pero primer contenido a los 9,6 s) y este guard lo
 * pilla.
 * Ejecución: node --experimental-strip-types --test scripts/portfolio-streaming-first-paint-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const source = (relativePath: string): string => readFileSync(join(root, relativePath), 'utf8');

describe('portfolio: primer pintado solo con la lectura esencial', () => {
    const page = source('app/(root)/portfolio/page.tsx');
    const tabs = source('components/portfolio/PortfolioTabs.tsx');

    it('la página no reintroduce await Promise.all', () => {
        assert.ok(!page.includes('await Promise.all'), 'page.tsx no debe volver a esperar a todas las lecturas');
        assert.ok(page.includes('await summaryPromise'), 'page.tsx solo espera summaryPromise antes de devolver JSX');
    });

    it('las lecturas tolerantes se pasan a PortfolioTabs como promesas', () => {
        for (const prop of ['transactionsPromise', 'scoresPromise', 'tearsheetPromise', 'forecastPromise', 'dividendsPromise']) {
            assert.ok(page.includes(prop), `page.tsx debe lanzar ${prop} sin esperarla`);
        }
    });

    it('cada panel tolerante se desenvuelve con use() dentro de <Suspense>', () => {
        assert.ok(tabs.includes('use(promise)'), 'PortfolioTabs desenvuelve las lecturas con use()');
        const boundaries = (tabs.match(/<Suspense /g) ?? []).length;
        assert.ok(boundaries >= 8, `esperaba >= 8 límites <Suspense> (aviso, botonera, gráfico, tearsheet, previsión, dividendos, movimientos y factores), hay ${boundaries}`);
        assert.ok(tabs.includes('fallback={<TabFallback />}'), 'los paneles tolerantes reservan sitio con TabFallback');
    });

    it('el gráfico NAV reserva su altura fija mientras llega la lectura', () => {
        assert.ok(tabs.includes('h-[200px]'), 'la caja de 200px del gráfico debe mantenerse para no desplazar el tearsheet');
        assert.ok(tabs.includes('NavChartLoading'), 'el fallback del gráfico anuncia la carga (role=status)');
    });
});
