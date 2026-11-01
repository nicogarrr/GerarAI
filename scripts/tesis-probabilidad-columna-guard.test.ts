/**
 * Guard: la columna «Probabilidad» de la tabla de escenarios de la lectura
 * publicada (/research/[ticker]/tesis) solo se rinde cuando algún escenario
 * trae probabilidad persistida por el motor; sin ese dato la columna entera
 * desaparece, porque un «N/D» triple aparentaría un dato que no existe
 * (regla de veracidad: nunca insinuar datos).
 * Ejecución: node --experimental-strip-types --test scripts/tesis-probabilidad-columna-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source: string = readFileSync('app/(root)/research/[ticker]/tesis/page.tsx', 'utf8');

void test('existe el flag hasProbabilities exigiendo probabilidad numérica real', () => {
    assert.match(
        source,
        /hasProbabilities\s*=\s*published\s*\?[\s\S]*?\.some\(\(p\) => typeof p === 'number'\)/,
        'hasProbabilities debe derivarse de las probabilidades persistidas (typeof number)',
    );
});

void test('la cabecera Probabilidad es condicional a hasProbabilities', () => {
    assert.match(
        source,
        /\{hasProbabilities \? <th[^>]*>\{t\('research\.thesisDoc\.colProbability'\)\}<\/th> : null\}/,
        'el th Probabilidad no puede rendirse cuando no hay probabilidades',
    );
});

void test('la celda de probabilidad es condicional a hasProbabilities', () => {
    assert.match(
        source,
        /\{hasProbabilities \? \(\s*<td[^>]*>\{typeof probability === 'number'/,
        'el td de probabilidad no puede rendirse cuando no hay probabilidades',
    );
});

void test('sin valores de escenario no se pinta la tabla y se dice tal cual', () => {
    assert.match(
        source,
        /hasScenarioValues\s*=\s*published\s*\?[\s\S]*?\.some\(\(v\) => v !== null\)/,
        'hasScenarioValues debe derivarse de los valores de escenario persistidos',
    );
    assert.match(
        source,
        /\{hasScenarioValues \? \(\s*<div[^>]*>\s*<table/,
        'la tabla de escenarios no puede rendirse sin valores de escenario',
    );
    assert.match(
        source,
        /\{t\('research\.thesisDoc\.noFigures'\)\}/,
        'sin valores debe mostrarse el mensaje honesto «Sin cifras de valoración.»',
    );
});
