/**
 * Render guard del panel de hipótesis de convergencia: el estado sin agregado
 * debe mostrar el motivo EXPLÍCITO del backend (assumptions) y nunca colapsar
 * un "no calculable" (monedas base mezcladas, FX N/D) en un falso vacío.
 *
 * El bundle corre con node --experimental-strip-types, que no transpila JSX:
 * el componente (y sus imports con alias @/) se transpilan aquí con la
 * TypeScript del repo a .mjs temporales bajo node_modules/.cache y se montan
 * con react-dom/server contra el payload real del endpoint.
 */
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import type { PortfolioForecast } from '../lib/actions/portfolio.actions';

const MIXED_BASE_PAYLOAD: PortfolioForecast = {
    as_of: null,
    base_currency: null,
    portfolio: null,
    positions: [],
    excluded: [
        {
            ticker: 'XYZ',
            name: 'Holding sin conversión',
            weight: null,
            currency: 'USD',
            reason: 'Sin valor en moneda base (conversión N/D): no se suma a la cartera.',
        },
    ],
    assumptions: [
        'Monedas base mezcladas entre posiciones: agregados de cartera N/D (no se suman monedas distintas).',
    ],
};

const REAL_EMPTY_PAYLOAD: PortfolioForecast = {
    as_of: null,
    base_currency: null,
    portfolio: null,
    positions: [],
    excluded: [],
    assumptions: ['Sin posiciones: no hay previsión que calcular.'],
};

async function renderForecast(payload: PortfolioForecast): Promise<string> {
    const ts = await import('typescript');
    const { mkdirSync, readFileSync, rmSync, writeFileSync } = await import('node:fs');
    const { createElement } = await import('react');
    const { renderToStaticMarkup } = await import('react-dom/server');

    const dir = 'node_modules/.cache/forecast-render';
    mkdirSync(dir, { recursive: true });
    const compile = (file: string) =>
        ts.transpileModule(readFileSync(file, 'utf8'), {
            compilerOptions: {
                jsx: ts.JsxEmit.ReactJSX,
                module: ts.ModuleKind.ESNext,
                target: ts.ScriptTarget.ES2022,
            },
            fileName: file,
        }).outputText;
    try {
        writeFileSync(`${dir}/utils.mjs`, compile('lib/utils.ts'));
        // format.ts importa el registro de locales (i18n): se compila también
        // y se reescribe la ruta al .mjs local, como con los demás stubs.
        writeFileSync(`${dir}/locale.mjs`, compile('lib/i18n/locale.ts'));
        writeFileSync(
            `${dir}/format.mjs`,
            compile('lib/format.ts').replaceAll("'./i18n/locale.ts'", "'./locale.mjs'"),
        );
        writeFileSync(
            `${dir}/panel.mjs`,
            compile('components/ui/panel.tsx').replaceAll('@/lib/utils', './utils.mjs'),
        );
        // El componente usa next/link para navegación SPA; fuera de Next se
        // monta con un stub que renderiza un <a> plano (mismo destino).
        writeFileSync(
            `${dir}/next-link.mjs`,
            `import { createElement } from 'react';
export default function Link({ href, children, ...rest }) { return createElement('a', { href, ...rest }, children); }
`,
        );
        writeFileSync(
            `${dir}/forecast.mjs`,
            compile('components/portfolio/PortfolioForecast.tsx').replaceAll(
                '@/components/ui/panel',
                './panel.mjs',
            ).replaceAll("'next/link'", "'./next-link.mjs'").replaceAll('@/lib/format', './format.mjs'),
        );
        const mod = await import(`${process.cwd()}/${dir}/forecast.mjs`);
        return renderToStaticMarkup(createElement(mod.default, { forecast: payload }));
    } finally {
        rmSync(dir, { recursive: true, force: true });
    }
}

describe('PortfolioForecast montado con react-dom/server', () => {
    it('con monedas base mezcladas muestra el motivo del backend y las excluidas, no un falso vacío', async () => {
        const html = await renderForecast(MIXED_BASE_PAYLOAD);
        assert.ok(html.includes('Monedas base mezcladas'), `debe mostrar la assumption del backend, obtuvo: ${html}`);
        assert.ok(html.includes('Excluidas del cálculo'), 'las excluidas siguen visibles en el estado sin agregado');
        assert.ok(html.includes('peso N/D'), 'el peso sin conversión se rotula N/D, nunca un cero');
        assert.ok(!html.includes('no hay previsión que calcular'), 'no puede colapsar a vacío real');
    });

    it('con cartera realmente vacía muestra el mensaje verbatim del backend', async () => {
        const html = await renderForecast(REAL_EMPTY_PAYLOAD);
        assert.ok(html.includes('Sin posiciones: no hay previsión que calcular.'), `vacío real verbatim, obtuvo: ${html}`);
    });

    it('los porcentajes se renderizan en formato es-ES con coma decimal', async () => {
        const { readFileSync } = await import('node:fs');
        const source = readFileSync('components/portfolio/PortfolioForecast.tsx', 'utf8');
        assert.ok(source.includes("Intl.NumberFormat('es-ES'"), 'el formato usa es-ES');
        assert.ok(!source.includes('.toFixed('), 'toFixed rompe la coma decimal es-ES');
        assert.ok(source.includes('Number.isFinite'), 'Infinity/NaN se filtran a Sin datos');
    });
});

it('los fixtures sin agregado conservan literalmente el copy vigente del backend', async () => {
    const {readFileSync} = await import('node:fs');
    const backend = readFileSync('data-engine/app/api/routes/portfolio.py','utf8');
    assert.ok(backend.includes(REAL_EMPTY_PAYLOAD.assumptions[0]));
    assert.ok(backend.includes(MIXED_BASE_PAYLOAD.excluded[0].reason));
});
