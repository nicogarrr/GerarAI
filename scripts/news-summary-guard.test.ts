import test from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { newsSummaryToShow } from '../lib/news-summary.ts';

test('resumen igual al titular no se pinta', () => {
    assert.equal(newsSummaryToShow('AST SpaceMobile lanza BlueBird 6', 'AST SpaceMobile lanza BlueBird 6.'), null);
    assert.equal(newsSummaryToShow('Titular', ''), null);
});

test('resumen que empieza por el titular pierde el titular', () => {
    assert.equal(newsSummaryToShow('Titular X', 'Titular X: la empresa confirma el plan.'), 'la empresa confirma el plan.');
});

test('resumen cortado a media palabra termina en palabra completa con puntos suspensivos', () => {
    const long = 'palabra '.repeat(25) + 'trunca';
    const out = newsSummaryToShow('Otro', long.slice(0, -2))!;
    assert.ok(out.endsWith('…'));
    assert.ok(!out.endsWith('trun…'));
});

test('resumen normal queda intacto', () => {
    assert.equal(newsSummaryToShow('A', 'Resumen completo.'), 'Resumen completo.');
});
