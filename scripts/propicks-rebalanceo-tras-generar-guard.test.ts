/**
 * Guard: el rebalanceo no puede quedarse con picks de un run viejo.
 *
 * Bug QA (2026-10-19): «Rebalanceo 0 valores tras generar picks». La caché
 * picksByStrategy solo comprobaba existencia (`!== undefined`): quien abría
 * «Estrategia y rebalanceo» sin run publicado cacheaba [] y, tras generar la
 * selección en «Selección IA», volvía al rebalanceo y veía «0 valores
 * vigentes» — la caché nunca se invalidaba.
 *
 * Fix: la caché guarda el asOf del run que la produjo y solo sirve si coincide
 * con el run vigente; cuando Selección IA genera/actualiza y llega un run
 * distinto, onRunUpdated invalida la caché de todas las estrategias.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/propicks-rebalanceo-tras-generar-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const tabs = readFileSync('components/proPicks/ProPicksTabs.tsx', 'utf8');
const content = readFileSync('components/proPicks/EnhancedProPicksContent.tsx', 'utf8');

describe('ProPicks: rebalanceo coherente con el run vigente', () => {
    it('la caché de estrategias guarda el asOf del run y exige coincidir con el vigente', () => {
        assert.match(tabs, /Record<string, \{ picks: ProPick\[\]; asOf: string \| null \}>/);
        assert.match(tabs, /cachedStrategyPicks\.asOf === latestRunAsOf/);
    });

    it('un run nuevo invalida la caché de todas las estrategias', () => {
        assert.match(tabs, /const handleRunUpdated = \(asOf: string \| null\)/);
        assert.match(tabs, /setPicksByStrategy\(\{\}\)/);
        assert.match(tabs, /onRunUpdated=\{handleRunUpdated\}/);
    });

    it('Selección IA avisa cuando la selección pasa a venir de otro run', () => {
        assert.match(content, /onRunUpdated\?: \(asOf: string \| null\) => void/);
        assert.match(content, /if \(result\.runAsOf !== lastGenerated\) onRunUpdated\?\.\(result\.runAsOf\)/);
    });
});
