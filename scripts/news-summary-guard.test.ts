import test from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { newsSummaryToShow } from '../lib/news-summary.ts';

test('resumen igual al titular no se pinta', () => {
    assert.equal(newsSummaryToShow('AST SpaceMobile lanza BlueBird 6', 'AST SpaceMobile lanza BlueBird 6.'), null);
    assert.equal(newsSummaryToShow('Titular', ''), null);
});

test('resumen que empieza por el titular pierde el titular y capitaliza', () => {
    assert.equal(newsSummaryToShow('Titular X', 'Titular X: la empresa confirma el plan.'), 'La empresa confirma el plan.');
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

test('titular recortado a media palabra no deja fragmento en el resumen', () => {
    const full = 'SpaceX (Space Exploration Technologies): Recibe una recomendación de compra del Bernstein MarketScreener España amplió cobertura ayer.';
    const cutTitle = full.slice(0, 86); // cae dentro de «Bernstein»
    const out = newsSummaryToShow(cutTitle, full)!;
    assert.ok(out.startsWith('MarketScreener'), `fragmento visible: ${out}`);
});

test('corte al final de palabra no pierde la palabra siguiente', () => {
    const out = newsSummaryToShow('Titular X', 'Titular X: la empresa confirma el plan.');
    assert.equal(out, 'La empresa confirma el plan.');
});

// Higiene de fragmentos (medido en prod 19-oct-2026: 18/30 resúmenes eran
// fragmentos feos o basura). Mejor sin resumen que un fragmento roto.
test('resumen que es solo el nombre de la fuente o restos no se pinta', () => {
    assert.equal(newsSummaryToShow('Titular', 'News TradingView', 'TradingView'), null);
    assert.equal(newsSummaryToShow('Titular', 'MarketScreener España', 'MarketScreener'), null);
    assert.equal(newsSummaryToShow('Titular', 'treet'), null);
    assert.equal(newsSummaryToShow('Titular', 'Wall Street'), null);
});

test('resumen que empieza a media frase se capitaliza al pintar', () => {
    assert.equal(newsSummaryToShow('Titular', 'payment services as their default rather than Apple Pay.'), 'Payment services as their default rather than Apple Pay.');
});

test('resumen sin cierre termina en puntos suspensivos', () => {
    const out = newsSummaryToShow('Titular', 'cloud provider Nscale was building for it, Reuters reported on October 18, citing the Telegraph. Microsoft is')!;
    assert.ok(out.endsWith('…'), `sin puntos suspensivos: ${out}`);
    assert.ok(out.startsWith('Cloud provider'), `sin capitalizar: ${out}`);
});

test('cola de titular sin cierre no se pinta', () => {
    assert.equal(newsSummaryToShow('Otro titular', 'Of Tesla — Sees Announcement In ‘Next Few Weeks’', 'Yahoo Finance'), null);
});

test('resumen que es un trozo del propio titular no se pinta', () => {
    const headline = 'JPMorgan brings deposit token JPM Coin to Ethereum for institutional clients';
    assert.equal(newsSummaryToShow(headline, 'deposit token JPM Coin to Ethereum'), null);
});

test('resumen sustancioso sin cierre se conserva y marca continuación', () => {
    const body = 'CEO Elon Musk challenged Anthropic’s plan to dedicate a portion of its ownership to public-benefit initiatives';
    assert.equal(newsSummaryToShow('Titular', body), `${body}…`);
});
