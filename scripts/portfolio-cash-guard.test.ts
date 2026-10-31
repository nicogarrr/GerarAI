/**
 * Guardas de la línea Caja de /portfolio (F81) y de la base de cada peso
 * (F104). La API devuelve `cash` como diccionario por moneda ya en divisa
 * base (RiskService.dashboard → calculate_portfolio_risk), NO como número:
 * el mapeo del frontend tiene que sumar los valores del diccionario.
 * Ejecución: node --experimental-strip-types --test scripts/portfolio-cash-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { sumCashByCurrency } from '../lib/portfolio-cash.ts';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { buildAllocationSlices, CASH_SLICE_SYMBOL } from '../lib/portfolio-allocation.ts';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const source = (relativePath: string): string => readFileSync(join(root, relativePath), 'utf8');

describe('sumCashByCurrency: respuesta real del backend { EUR: 100 }', () => {
    it('suma los valores del diccionario por moneda', () => {
        assert.equal(sumCashByCurrency({ EUR: 100 }), 100);
        assert.equal(sumCashByCurrency({ EUR: 1234.56 }), 1234.56);
        assert.equal(sumCashByCurrency({ EUR: 100, USD: 50 }), 150);
    });

    it('sin caja o caja vacía es 0: la línea Caja no se muestra', () => {
        assert.equal(sumCashByCurrency({}), 0);
        assert.equal(sumCashByCurrency(null), 0);
        assert.equal(sumCashByCurrency(undefined), 0);
        assert.equal(sumCashByCurrency({ EUR: 0 }), 0);
    });

    it('valores no finitos no contaminan la suma', () => {
        assert.equal(sumCashByCurrency({ EUR: Number.NaN }), 0);
        assert.equal(sumCashByCurrency({ EUR: Number.POSITIVE_INFINITY, USD: 25 }), 25);
    });
});

describe('contrato y mapeo del resumen', () => {
    it('el contrato declara cash como diccionario por moneda, no como número', () => {
        const actions = source('lib/actions/portfolio.actions.ts');
        // El contrato del resumen es el schema generado desde el OpenAPI del
        // backend (response_model en la ruta), no un tipo manuscrito.
        assert.ok(actions.includes("components['schemas']['PortfolioSummaryOut']"), 'el resumen usa el tipo generado desde el OpenAPI');
        const generated = source('lib/research/openapi.generated.ts');
        const start = generated.indexOf('PortfolioSummaryOut: {');
        const block = generated.slice(start, start + 2000);
        const cashField = /cash: \{\s*\[key: string\]: number;\s*\}/;
        assert.ok(cashField.test(block), 'cash tipado como diccionario por moneda');
        assert.ok(!/cash: number/.test(block), 'cash no puede tiparse como número: con el payload real la línea no se mostraría');
    });

    it('getPortfolioSummary deriva el importe con sumCashByCurrency', () => {
        const actions = source('lib/actions/portfolio.actions.ts');
        assert.ok(actions.includes('cash: sumCashByCurrency(backendSummary.cash)'), 'mapeo desde el diccionario del backend');
    });
});

describe('línea Caja en las tablas de posiciones', () => {
    it('móvil y escritorio muestran la línea Caja solo con caja distinta de 0', () => {
        const holdings = source('components/portfolio/PortfolioHoldings.tsx');
        assert.ok(holdings.includes("typeof cash === 'number' && cash !== 0"), 'condición explícita sobre el importe derivado');
        assert.ok(holdings.includes('border-dashed'), 'tarjeta móvil de caja diferenciada');
        // La etiqueta vive en el diccionario i18n; el componente referencia la clave
        // en móvil y escritorio y el valor es 'Caja'.
        assert.ok((holdings.match(/portfolio\.holdings\.cash/g) ?? []).length >= 2, 'una línea Caja en móvil y otra en escritorio');
        const dict = JSON.parse(readFileSync(join(root, 'lib/i18n/messages/es/portfolio.json'), 'utf8'));
        assert.equal(dict.holdings.cash, 'Caja', 'etiqueta de la línea en el diccionario es');
    });

    it('PortfolioTabs pasa cash y moneda base a la tabla', () => {
        const tabs = source('components/portfolio/PortfolioTabs.tsx');
        assert.ok(tabs.includes('cash={summary.cash}'), 'cash hacia PortfolioHoldings');
        assert.ok(tabs.includes('baseCurrency={summary.baseCurrency}'), 'moneda base hacia PortfolioHoldings');
    });
});

describe('buildAllocationSlices: datos del donut', () => {
    it('reparte pesos SOLO entre posiciones (suman 100%): la caja nunca es segmento', () => {
        const slices = buildAllocationSlices([
            { symbol: 'MSFT', value: 100, gain: 0, gainPercent: 0 },
            { symbol: 'AAPL', value: 300, gain: 0, gainPercent: 0 },
        ]);
        assert.equal(slices.length, 2);
        assert.equal(slices[0].symbol, 'AAPL');
        assert.equal(slices[0].percentage, 75);
        assert.equal(slices[1].percentage, 25);
        assert.ok(slices.every((slice) => slice.symbol !== CASH_SLICE_SYMBOL), 'sin segmento Caja');
    });

    it('con margen (caja negativa) los pesos no superan el 100%', () => {
        // Caso real 11 oct 2026: RV 21.520,40 + caja -11.269,38 daba ASTS 133,1%.
        const slices = buildAllocationSlices([
            { symbol: 'ASTS', value: 13635, gain: 0, gainPercent: 0 },
            { symbol: 'TSLA', value: 7885.4, gain: 0, gainPercent: 0 },
        ]);
        const total = slices.reduce((acc, slice) => acc + slice.percentage, 0);
        assert.ok(Math.abs(total - 100) < 1e-9, 'los pesos suman 100');
        assert.equal(slices[0].percentage, (13635 / 21520.4) * 100);
    });

    it('sin posiciones no hay slices: la caja va en su línea aparte', () => {
        assert.equal(buildAllocationSlices([]).length, 0);
    });

    it('la etiqueta declara la base y el panel no se esconde con cartera solo-caja', () => {
        const allocation = source('components/portfolio/PortfolioAllocation.tsx');
        assert.ok(allocation.includes('portfolio.allocation.weightsNote'), 'etiqueta que declara la base vía i18n');
        const dictBase = JSON.parse(readFileSync(join(root, 'lib/i18n/messages/es/portfolio.json'), 'utf8'));
        assert.equal(dictBase.allocation.weightsNote, 'Pesos sobre el valor bruto de las posiciones', 'valor es de la etiqueta de base');
        assert.ok(allocation.includes('holdings.length === 0 && !hasCash'), 'estado vacío solo cuando tampoco hay caja');
        assert.ok(allocation.includes('buildAllocationSlices(knownHoldings)'), 'datos vía el helper probado');
    });

    it('la leyenda no enlaza la caja', () => {
        const allocation = source('components/portfolio/PortfolioAllocation.tsx');
        assert.ok(allocation.includes('item.symbol === CASH_SLICE_SYMBOL'), 'la leyenda distingue la caja');
    });

    it('una posición sin valor no certifica un 100% falso: fuera del donut y con aviso', () => {
        // Regresión: valor ausente o suspendido no entra como cero; coste pendiente sí entra.
        // El criterio anterior valueMissing/fxMissing mapeaba a 0 y el
        // reparto normalizaba lo conocido al 100% sin decirlo.
        const allocation = source('components/portfolio/PortfolioAllocation.tsx');
        assert.ok(
            allocation.includes('!holding.valueMissing && !holding.valuationHold'),
            'el panel filtra posiciones sin valor conocido antes de repartir',
        );
        const dictAv = JSON.parse(readFileSync(join(root, 'lib/i18n/messages/es/portfolio.json'), 'utf8'));
        assert.ok(allocation.includes('portfolio.allocation.incomplete'), 'aviso visible cuando falta alguna (clave i18n)');
        assert.ok(dictAv.allocation.incomplete.includes('Distribución incompleta'), 'valor es del aviso');
        assert.ok(allocation.includes('portfolio.allocation.noValues'), 'abstención cuando ninguna tiene valor (clave i18n)');
        assert.ok(dictAv.allocation.noValues.includes('Distribución N/D'), 'valor es de la abstención');
    });

    it('la caja/margen va en línea aparte con su signo real, fuera del donut', () => {
        const allocation = source('components/portfolio/PortfolioAllocation.tsx');
        const dictCaja = JSON.parse(readFileSync(join(root, 'lib/i18n/messages/es/portfolio.json'), 'utf8'));
        assert.ok(allocation.includes('portfolio.allocation.cashMargin'), 'etiqueta de margen cuando la caja es negativa (clave i18n)');
        assert.equal(dictCaja.allocation.cashMargin, 'Caja (margen)', 'valor es de la etiqueta de margen');
        assert.ok(allocation.includes('formatMoney(cash,'), 'importe real formateado, sin suavizar el signo');
        assert.ok(allocation.includes("typeof cash === 'number' && cash !== 0"), 'la línea aparece con cualquier signo');
    });
});

describe('AllocationTooltip montado con react-dom/server', () => {
    it('la caja en cartera EUR muestra euros, no dólares, y sin enlace ni G/P', async () => {
        const { renderToStaticMarkup } = await import('react-dom/server');
        const { createElement } = await import('react');
        // @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
        const { AllocationTooltip } = await import('../components/portfolio/AllocationTooltip.ts');
        const html = renderToStaticMarkup(createElement(AllocationTooltip, {
            active: true,
            currency: 'EUR',
            payload: [{ payload: { symbol: 'Caja', value: 100, percentage: 100, gain: 0, gainPercent: 0 } }],
        }));
        assert.ok(html.includes('€'), `importe en EUR esperado, obtuvo: ${html}`);
        assert.ok(!html.includes('US$') && !html.includes('USD'), 'no puede renderizar la cifra en dólares');
        assert.ok(!html.includes('/research/Caja'), 'la caja no enlaza a una ficha inexistente');
        assert.ok(!html.includes('G/P'), 'la caja no muestra una G/P inventada');
    });

    it('una acción enlaza su ficha y muestra G/P con la moneda recibida', async () => {
        const { renderToStaticMarkup } = await import('react-dom/server');
        const { createElement } = await import('react');
        // @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
        const { AllocationTooltip } = await import('../components/portfolio/AllocationTooltip.ts');
        const html = renderToStaticMarkup(createElement(AllocationTooltip, {
            active: true,
            currency: 'EUR',
            payload: [{ payload: { symbol: 'AAPL', value: 300, percentage: 75, gain: 30, gainPercent: 10 } }],
        }));
        assert.ok(html.includes('/research/AAPL'), 'la acción enlaza su ficha');
        assert.ok(html.includes('G/P'), 'la acción muestra su G/P');
        assert.ok(html.includes('€'), 'importe en la moneda base recibida');
    });

    it('las etiquetas por defecto del tooltip coinciden con el diccionario es', async () => {
        const { readFileSync } = await import('node:fs');
        const dict = JSON.parse(readFileSync(new URL('../lib/i18n/messages/es/portfolio.json', import.meta.url), 'utf8'));
        const src = source('components/portfolio/AllocationTooltip.ts');
        for (const [key, value] of Object.entries(dict.allocationTooltip)) {
            assert.ok(src.includes(`'${value}'`), `DEFAULT_LABELS.${key} debe ser '${value}' del diccionario es`);
        }
    });

    it('la moneda base llega desde el summary hasta el tooltip', () => {
        const tabs = source('components/portfolio/PortfolioTabs.tsx');
        assert.ok(tabs.includes('baseCurrency={summary.baseCurrency}'), 'PortfolioTabs pasa la moneda base');
        const allocation = source('components/portfolio/PortfolioAllocation.tsx');
        assert.ok(allocation.includes('currency={baseCurrency}'), 'Allocation la pasa al chart');
        const chart = source('components/portfolio/PortfolioAllocationChart.tsx');
        assert.ok(chart.includes('currency={currency}'), 'el chart la pasa al tooltip');
    });
});

describe('cartera solo-caja en la tabla de posiciones', () => {
    it('la línea Caja aparece aunque no haya posiciones abiertas', () => {
        const holdings = source('components/portfolio/PortfolioHoldings.tsx');
        assert.ok(holdings.includes('currentHoldings.length === 0 && !showCash'), 'estado vacío solo cuando tampoco hay caja');
    });
});
