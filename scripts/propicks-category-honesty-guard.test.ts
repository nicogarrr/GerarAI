/**
 * Guard F184: una categoría del pick sin datos para todo el universo cae a
 * 50 neutral (flag `*_neutral_sin_datos` en facts) y NO puede pintarse como
 * un score real: la tarjeta muestra «n/d*» con nota al pie, y los textos de
 * /propicks declaran que en v1 discriminan 4 categorías mientras valoración
 * y momentum entran neutras. Antes: el intro prometía «6 categorías (…,
 * momentum, …)», la caja decía «✗ … aún no (v1)» y cada tarjeta pintaba
 * «Valor 50 / Momentum 50» como si fueran scores reales.
 * Ejecución: node --experimental-strip-types --test scripts/propicks-category-honesty-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { categoryDisplay } from '../lib/propicks/category-display.ts';

type Facts = Record<string, number | string>;
import type { ProPick } from '../lib/actions/proPicks.actions.ts';
// Los textos de Pro Picks viven en el diccionario es (i18n): se comprueban junto al código.
const ES_PROPICKS_JSON = readFileSync(new URL('../lib/i18n/messages/es/propicks.json', import.meta.url), 'utf8');
const pickWith = (facts: Facts): ProPick => ({
    facts,
    categoryScores: { value: 50, growth: 80, profitability: 94, cashFlow: 70, momentum: 50, debtLiquidity: 60 },
} as ProPick);

void test('categoría con flag neutral -> n/d, nunca el 50', () => {
    assert.deepEqual(categoryDisplay(pickWith({ valoracion_neutral_sin_datos: 'si' }), 'value'), { kind: 'neutral' });
    assert.deepEqual(categoryDisplay(pickWith({ momentum_neutral_sin_datos: 'si' }), 'momentum'), { kind: 'neutral' });
    assert.deepEqual(categoryDisplay(pickWith({ moat_neutral_sin_datos: 'si' }), 'profitability'), { kind: 'neutral' });
    // La deuda de bancos también es neutral aunque el flag sea otro.
    assert.deepEqual(categoryDisplay(pickWith({ deuda_neutral_banco: 'si' }), 'debtLiquidity'), { kind: 'neutral' });
});

void test('categoría con datos -> su score real', () => {
    assert.deepEqual(categoryDisplay(pickWith({}), 'profitability'), { kind: 'score', value: 94 });
    // Un flag de OTRA categoría no apaga esta.
    assert.deepEqual(categoryDisplay(pickWith({ momentum_neutral_sin_datos: 'si' }), 'growth'), { kind: 'score', value: 80 });
});

void test('las tarjetas pintan n/d con nota al pie y los textos declaran las neutras', () => {
    const cards: string = (readFileSync(new URL('../components/proPicks/EnhancedProPicksContent.tsx', import.meta.url), 'utf8') + ES_PROPICKS_JSON);
    assert.match(cards, /categoryDisplay\(pick, key\)/);
    assert.match(cards, /display\.kind === 'neutral'/);
    assert.match(cards, /n\/d\*/);
    assert.match(cards, /entra neutral \(50\) en el score y no discrimina entre los picks actuales/);
    assert.ok(!cards.includes('Sobre ProPicks IA'), 'el bloque informativo se eliminó');
    assert.ok(!cards.includes('aún no (v1)'), 'la caja ya no contradice el mecanismo real');

    const page: string = (readFileSync(new URL('../app/(root)/propicks/page.tsx', import.meta.url), 'utf8') + ES_PROPICKS_JSON);
    assert.match(page, /entran\s*\n?\s*neutras\s*\n?\s*\(50\) y se marcan n\/d en las tarjetas/);
    assert.ok(!/6 categorías\s*\n?\s*\(valor/.test(page), 'el intro ya no promete 6 categorías con valor y momentum');
});

void test('la causalidad es la real: valoración <- CFROI/WACC, momentum <- precios', () => {
    // F184 iteración auditor: el copy NO puede atribuir la valoración
    // neutral a la falta de series de precios (la valoración se calcula de
    // cfroi_approx y wacc; el flag salta si falta cualquiera).
    const page: string = (readFileSync(new URL('../app/(root)/propicks/page.tsx', import.meta.url), 'utf8') + ES_PROPICKS_JSON);
    const cards: string = (readFileSync(new URL('../components/proPicks/EnhancedProPicksContent.tsx', import.meta.url), 'utf8') + ES_PROPICKS_JSON);
    for (const [name, text] of [['intro', page]] as const) {
        assert.match(text, /la\s+valoración necesita CFROI y WACC/, `${name}: la valoración neutral debe atribuirse a CFROI/WACC`);
    }
    // Construcción prohibida: «sin series de precios ... entran neutras»
    // atribuyendo la neutralidad de AMBAS categorías solo a precios.
    assert.ok(
        !/sin\s*\n?\s*series de precios para todo el universo\s*\n?\s*entran\s*\n?\s*neutras/.test(page + cards),
        'prohibido atribuir la neutralidad de valoración y momentum solo a las series de precios',
    );
    // Ningún absoluto de cobertura: no se puede prometer «datos para todo
    // el universo» en categorías que también tienen flags de ausencia.
    assert.ok(
        !/categorías con datos para todo el universo/.test(page),
        'el intro no puede prometer cobertura completa de ninguna categoría',
    );
});

void test('el filtro de orden deshabilita las categorías neutras de todo el run', () => {
    const content: string = (readFileSync(new URL('../components/proPicks/EnhancedProPicksContent.tsx', import.meta.url), 'utf8') + ES_PROPICKS_JSON);
    assert.match(content, /neutralSorts=\{\(\['momentum', 'value'\] as const\)\.filter\(\(key\) => allNeutralCategory\(picks, key\)\)\}/);
    const filters: string = (readFileSync(new URL('../components/proPicks/EnhancedProPicksFilters.tsx', import.meta.url), 'utf8') + ES_PROPICKS_JSON);
    assert.match(filters, /disabled=\{neutralSorts\.includes\('momentum'\)\}/);
    assert.match(filters, /disabled=\{neutralSorts\.includes\('value'\)\}/);
    assert.match(filters, /\(n\/d en estos resultados\)/);
});

void test('allNeutralCategory: true solo si TODOS los picks son neutros en la categoría', async () => {
    // @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
    const mod = await import('../lib/propicks/category-display.ts');
    const todos = [pickWith({ momentum_neutral_sin_datos: 'si' }), pickWith({ momentum_neutral_sin_datos: 'si' })];
    const mixtos = [pickWith({ momentum_neutral_sin_datos: 'si' }), pickWith({})];
    assert.equal(mod.allNeutralCategory(todos, 'momentum'), true);
    assert.equal(mod.allNeutralCategory(mixtos, 'momentum'), false);
    assert.equal(mod.allNeutralCategory([], 'momentum'), false);
});

console.log('propicks-category-honesty-guard: ok');
