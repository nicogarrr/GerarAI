/**
 * F383: cambiar de estrategia debe cargar los picks de esa estrategia; el
 * rebalanceo y el export JSON no pueden llevar los picks de otra.
 * Ejecución: node --experimental-strip-types --test scripts/propicks-strategy-switch-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const tabs = readFileSync('components/proPicks/ProPicksTabs.tsx', 'utf8');
const view = readFileSync('components/proPicks/MonthlyRebalanceView.tsx', 'utf8');

describe('cambio de estrategia ProPicks (F383)', () => {
    it('carga picks por estrategia y no pasa initialPicks al rebalanceo', () => {
        assert.match(tabs, /generateProPicksForStrategy\(currentStrategy\)/);
        assert.doesNotMatch(tabs, /currentPicks=\{initialPicks\}/);
        assert.match(tabs, /currentPicks=\{strategyPicks \?\? \[\]\}/);
    });
    it('la estrategia inicial tampoco reutiliza initialPicks', () => {
        assert.doesNotMatch(tabs, /\[initialStrategyId\]: initialPicks/);
        assert.match(tabs, /useState<Record<string, \{ picks: ProPick\[\]; asOf: string \| null \}>>\(\{\}\)/);
    });
    it('el snapshot anterior se descarta al cambiar de estrategia (key)', () => {
        assert.match(tabs, /<MonthlyRebalanceView\s+key=\{currentStrategy\}/);
    });
    it('el export se bloquea mientras los picks no estén listos', () => {
        assert.match(view, /disabled=\{picksStatus !== 'ready'\}/);
        assert.match(view, /if \(picksStatus !== 'ready'\) return;/);
    });
});
