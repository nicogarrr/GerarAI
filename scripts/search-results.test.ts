import assert from 'node:assert/strict';
import { test } from 'node:test';
// @ts-expect-error TS5097
import { exactSymbolFirst, marketPriority, onePerIssuer } from '../lib/market/search-results.ts';

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

test('KO: el ticker exacto US gana a los listados con sufijo del mismo emisor', () => {
    const rows = [
        { symbol: 'KO.MX', description: 'COCA-COLA CO/THE' },
        { symbol: 'KO.VI', description: 'COCA-COLA CO/THE' },
        { symbol: 'KOMATSU', description: 'KOMATSU LTD' },
        { symbol: 'KO', description: 'COCA-COLA CO/THE' },
    ];
    const out = onePerIssuer(exactSymbolFirst(rows, 'KO'), 'KO').map((r: { symbol: string }) => r.symbol);
    assert.deepEqual(out, ['KO', 'KOMATSU']);
});

test('ASTS: el ticker exacto se conserva primero aunque otros nombres coincidan', () => {
    const rows = [
        { symbol: 'ASTSF', description: 'ASTRA SPACE' },
        { symbol: 'ASTS', description: 'AST SPACEMOBILE INC' },
    ];
    const out = onePerIssuer(exactSymbolFirst(rows, 'ASTS'), 'ASTS').map((r: { symbol: string }) => r.symbol);
    assert.equal(out[0], 'ASTS');
});

test('sin ticker exacto el comportamiento previo no cambia', () => {
    const rows = [
        { symbol: 'ASML', description: 'ASML HOLDING NV-NY REG SHS' },
        { symbol: 'ASML.AS', description: 'ASML HOLDING NV' },
    ];
    assert.deepEqual(onePerIssuer(rows, 'ASML HOLDING').map((r: { symbol: string }) => r.symbol), ['ASML.AS']);
});

test('marketPriority pone EE. UU. antes que bolsas secundarias (CPT Camden antes que CPT.BK)', () => {
    const rows = [
        { symbol: 'CPT.BK', description: 'CAPITAL TRUST' },
        { symbol: 'CPT.SW', description: 'CPT SA' },
        { symbol: 'CPTX', description: 'CAMDEN PROPERTY TRUST' },
        { symbol: 'CPT.MC', description: 'CPT' },
    ];
    assert.deepEqual(marketPriority(rows, 'CPT').map((r: { symbol: string }) => r.symbol), ['CPTX', 'CPT.SW', 'CPT.MC', 'CPT.BK']);
    const exact = [{ symbol: 'ABC.BK' }, { symbol: 'ABC' }];
    assert.equal(marketPriority(exact, 'ABC.BK')[0].symbol, 'ABC.BK');
});
