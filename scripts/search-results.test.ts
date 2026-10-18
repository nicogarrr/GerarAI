import assert from 'node:assert/strict';
import { test } from 'node:test';
// @ts-expect-error TS5097
import { exactSymbolFirst, onePerIssuer } from '../lib/market/search-results.ts';

test('oculta el simbolo desnudo cuando existe el listado base del mismo emisor', () => {
    const rows = [
        { symbol: 'ASML', description: 'ASML HOLDING NV-NY REG SHS' },
        { symbol: 'ASML.AS', description: 'ASML HOLDING NV' },
    ];
    assert.deepEqual(onePerIssuer(rows).map((r: { symbol: string }) => r.symbol), ['ASML.AS']);
});

test('no funde emisores distintos con el mismo simbolo base', () => {
    const rows = [
        { symbol: 'ALM', description: 'ALMONTY INDUSTRIES INC' },
        { symbol: 'ALM.MC', description: 'ALMIRALL SA' },
    ];
    assert.equal(onePerIssuer(rows).length, 2);
});

test('coincidencia exacta primero y orden estable', () => {
    const rows = [
        { symbol: 'SAP.TO', description: 'SAPUTO INC' },
        { symbol: 'SAP', description: 'SAP SE-SPONSORED ADR' },
        { symbol: 'SAPR', description: 'X' },
    ];
    assert.deepEqual(exactSymbolFirst(rows, 'sap').map((r: { symbol: string }) => r.symbol), ['SAP', 'SAP.TO', 'SAPR']);
});
