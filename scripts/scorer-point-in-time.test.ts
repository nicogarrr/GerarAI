/**
 * Test: el asOf del scorer FILTRA, no etiqueta (V3).
 *
 * Antes: `resolvedAsOf` se devolvía como etiqueta mientras el cálculo de
 * momentum y los `facts` consumían TODAS las velas, incluidas las posteriores
 * al corte (repro: corte 2021-01-01 con una vela de 2026 subía momentum
 * 35 -> 80 y facts mostraba retornos +400 % con etiqueta 2021).
 *
 * Ejecución: node --experimental-strip-types --test scripts/scorer-point-in-time.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { filterCandlesUpTo } from '../lib/utils/candleCutoff.ts';

const DAY = 86400;
const T_2021 = 1609459200; // 2021-01-01T00:00:00Z

describe('filterCandlesUpTo: el corte excluye velas futuras', () => {
    const series = {
        dates: [T_2021 - 2 * DAY, T_2021 - DAY, T_2021 + DAY, T_2021 + 2 * DAY],
        prices: [98, 99, 500, 600],
    };

    it('una vela posterior al corte no entra en el cálculo', () => {
        const filtered = filterCandlesUpTo(series, '2021-01-01T00:00:00Z');
        assert.deepEqual(filtered.prices, [98, 99]);
        assert.deepEqual(filtered.dates, [T_2021 - 2 * DAY, T_2021 - DAY]);
    });

    it('la vela exactamente en el corte sí entra (<=)', () => {
        const filtered = filterCandlesUpTo(
            { dates: [T_2021], prices: [100] },
            '2021-01-01T00:00:00Z',
        );
        assert.deepEqual(filtered.prices, [100]);
    });

    it('sin velas dentro de la ventana devuelve serie vacía (no inventa)', () => {
        const filtered = filterCandlesUpTo(series, '2020-01-01T00:00:00Z');
        assert.deepEqual(filtered, { prices: [], dates: [] });
    });

    it('un corte no parseable devuelve la serie intacta (lo decide el llamador)', () => {
        const filtered = filterCandlesUpTo(series, 'no-es-una-fecha');
        assert.equal(filtered, series);
    });
});

describe('advancedStockScoring: contrato de fuente point-in-time', () => {
    const source = readFileSync('lib/utils/advancedStockScoring.ts', 'utf8');

    it('las velas se filtran por resolvedAsOf antes de puntuar', () => {
        assert.match(source, /filterCandlesUpTo\(historicalData, resolvedAsOf\)/);
    });

    it('momentum y facts usan las velas filtradas, nunca historicalData en crudo', () => {
        assert.doesNotMatch(source, /historicalData\.prices/);
        // La única lectura de dates en crudo es la que deriva el corte por
        // defecto (última vela); todo lo demás usa la serie filtrada.
        const rawDatesUses = source.match(/historicalData\.dates/g) ?? [];
        assert.equal(rawDatesUses.length, 3); // guarda + índice + length en lastCandleTs
        assert.match(source, /historicalData\.dates\.length > 0/);
    });

    it('la cotización con timestamp posterior al corte no alimenta el cambio diario', () => {
        assert.match(source, /quoteAfterCutoff/);
        assert.match(source, /quote\.dp && !quoteAfterCutoff/);
    });
});
