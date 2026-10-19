import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('Spanish snapshot stays synchronized with every explicit reviewed CNMV listing', () => {
    const source = readFileSync('data-engine/app/services/cnmv_mapping.py', 'utf8');
    const expected = [...source.matchAll(/CNMVIssuer\("[^"]+", "([^"]+)", "[^"]+", "[^"]+", \(([^\n]+)\)\),/g)]
        .map((match) => ({ name: match[1], aliases: [...match[2].matchAll(/"([^"]+)"/g)].map((x) => x[1]) }))
        .filter((row) => row.aliases.some((alias) => alias.endsWith('.MC')))
        .map((row) => ({ symbol: row.aliases.find((alias) => alias.endsWith('.MC')),
            aliases: row.aliases, name: row.aliases.includes('INDITEX') ? 'Inditex (Industria de Diseño Textil)' : row.name }));
    assert.ok(expected.length > 50, 'parser must read the reviewed table, not silently accept empty data');
    const actual = JSON.parse(readFileSync('lib/market/spanish-listings.json', 'utf8'));
    assert.deepEqual(actual, expected);
});
