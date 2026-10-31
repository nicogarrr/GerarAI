/**
 * Nivel DCA + valor justo único en Cartera e Inicio: mapeo puro y degradación «sin nivel».
 * Ejecución: node --experimental-strip-types --test scripts/holding-signals.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
    dcaLevelText,
    fairValueGapPercent,
    mapDcaSignals,
    mapFairValues,
    NO_DCA_LEVEL,
    // @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
} from '../lib/portfolio/holding-signals.ts';

describe('valor justo único por posición', () => {
    it('mapea solo lecturas válidas, con su etiqueta de procedencia', () => {
        const out = mapFairValues({
            precedence: '…',
            items: {
                pool: { value: 400, source: 'tesis', label: 'Tesis publicada v3', as_of: '2026-10-01', currency: 'USD', publishable: true },
                UBER: { value: 90, source: 'motor_orientativo', label: 'Motor de valoración (orientativo)', as_of: null, currency: 'USD', publishable: false },
                NADA: { value: null, source: null, label: 'Sin valor justo' },
                RARO: { value: 10, source: 'inventado', label: 'x' },
                NEG: { value: -5, source: 'motor', label: 'Motor de valoración' },
            },
        });
        assert.deepEqual(Object.keys(out).sort(), ['POOL', 'UBER']);
        assert.equal(out.POOL.label, 'Tesis publicada v3');
        assert.equal(out.UBER.publishable, false);
    });

    it('respuesta rota o vacía no rompe: mapa vacío', () => {
        assert.deepEqual(mapFairValues(null), {});
        assert.deepEqual(mapFairValues({ items: [] }), {});
    });

    it('margen frente al precio solo con la MISMA divisa', () => {
        const fair = { value: 120, source: 'motor', label: 'Motor de valoración', asOf: null, currency: 'USD', publishable: true } as const;
        assert.equal(fairValueGapPercent(100, 'USD', fair), 20);
        assert.equal(fairValueGapPercent(100, 'usd', fair), 20);
        assert.equal(fairValueGapPercent(100, 'GBX', fair), null, 'peniques frente a dólares: no se mezcla');
        assert.equal(fairValueGapPercent(null, 'USD', fair), null);
        assert.equal(fairValueGapPercent(0, 'USD', fair), null);
        assert.equal(fairValueGapPercent(100, 'USD', null), null);
    });
});

describe('nivel DCA por posición', () => {
    it('mapea el estado del motor por ticker y marca el mes en formación', () => {
        const out = mapDcaSignals({
            items: [
                { symbol: 'pool', state: { level: 4, label: '4X DCA', status: 'forming', signal_date: '2026-10-26', color: '#B400FF', fg: '#FFFFFF' } },
                { symbol: 'AAPL', state: { level: 1, label: '1X DCA', status: 'confirmed', signal_date: '2026-09-30' } },
                { symbol: 'HIMS', state: null },
            ],
        });
        assert.ok(out);
        assert.deepEqual(Object.keys(out).sort(), ['AAPL', 'POOL']);
        assert.equal(dcaLevelText(out.POOL), '4X DCA (provisional)');
        assert.equal(dcaLevelText(out.AAPL), '1X DCA');
        assert.equal(dcaLevelText(out.HIMS), NO_DCA_LEVEL);
    });

    it('sin motor DCA (endpoint ausente o respuesta inválida) degrada a «Sin nivel»', () => {
        assert.equal(mapDcaSignals(null), null);
        assert.equal(mapDcaSignals({ detail: 'Not Found' }), null);
        assert.equal(dcaLevelText(null), 'Sin nivel');
    });
});

describe('cableado en Cartera e Inicio', () => {
    const action = readFileSync('lib/actions/holding-signals.actions.ts', 'utf8');
    const holdings = readFileSync('components/portfolio/PortfolioHoldings.tsx', 'utf8');
    const home = readFileSync('components/PersonalizedOverview.tsx', 'utf8');

    it('una petición por lote para el valor justo y el endpoint del motor DCA, cada una degrada sola', () => {
        assert.match(action, /\/api\/valuation\/fair-value\?tickers=/);
        assert.match(action, /\/api\/watchlist\/dca-signals/);
        assert.match(action, /Promise\.allSettled/);
    });

    it('la tabla de posiciones y el inicio pintan nivel DCA y valor justo', () => {
        // i18n: la cabecera vive en messages/<locale>/portfolio.json.
        assert.match(holdings, /portfolio\.holdings\.colDcaFair/);
        const portfolioEs = JSON.parse(readFileSync('lib/i18n/messages/es/portfolio.json', 'utf8'));
        assert.equal(portfolioEs.holdings.colDcaFair, 'DCA · Valor justo');
        assert.match(holdings, /<DcaLevelChip symbol=\{holding\.symbol\}/);
        assert.match(holdings, /<FairValueLine symbol=\{holding\.symbol\}/);
        assert.match(home, /<DcaLevelChip symbol=\{h\.symbol\}/);
        assert.match(home, /<HomeFairValueHint holding=\{h\}/);
    });
});
