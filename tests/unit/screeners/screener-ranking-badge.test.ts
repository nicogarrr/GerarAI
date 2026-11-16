/**
 * Insignia «ranking: …» de los resultados del screener: antes era un
 * literal hardcodeado en inglés con la dirección cruda del backend
 * («ranking: roic - wacc · desc»). Regresión: debe usar la clave i18n
 * screener.rankingBadge (huérfana conocida desde D1 a la espera de su
 * consumidor) con la fórmula legible y la dirección traducida.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { screenRankingFormulaLabel } from '@/lib/screener-results';
import es from '@/lib/i18n/messages/es/screener.json';
import en from '@/lib/i18n/messages/en/screener.json';

describe('screenRankingFormulaLabel', () => {
    it('métrica conocida: etiqueta legible + slug reconocible (es)', () => {
        expect(screenRankingFormulaLabel('market_cap', 'es')).toBe('Capitalización bursátil (market_cap)');
    });
    it('métrica conocida: etiqueta legible + slug reconocible (en)', () => {
        expect(screenRankingFormulaLabel('market_cap', 'en')).toBe('Market capitalization (market_cap)');
    });
    it('fórmula libre: se muestra tal cual, nunca reinterpretada', () => {
        expect(screenRankingFormulaLabel('roic - wacc', 'es')).toBe('roic - wacc');
    });
    it('recorta espacios del valor del backend', () => {
        expect(screenRankingFormulaLabel('  market_cap  ', 'es')).toBe('Capitalización bursátil (market_cap)');
    });
    it('vacío: N/D honesto, nunca una insignia vacía', () => {
        expect(screenRankingFormulaLabel('', 'es')).toBe('N/D');
        expect(screenRankingFormulaLabel('   ', 'en')).toBe('N/A');
    });
});

describe('la página de screeners usa la clave i18n, no un literal', () => {
    const source = readFileSync('app/(root)/screeners/page.tsx', 'utf8');

    it('sin el literal hardcodeado «ranking: {result.ranking_formula}»', () => {
        expect(source).not.toContain('ranking: {result.ranking_formula}');
    });
    it('consume la clave screener.rankingBadge (huérfana D1 con consumidor)', () => {
        expect(source).toContain("t('screener.rankingBadge'");
    });
    it('traduce la dirección con las claves existentes, nunca «desc» crudo', () => {
        expect(source).toContain("t('screener.screens.desc')");
        expect(source).toContain("t('screener.screens.asc')");
    });
});

describe('la clave screener.rankingBadge conserva sus placeholders en los dos idiomas', () => {
    it('es', () => {
        expect(es.rankingBadge).toContain('{formula}');
        expect(es.rankingBadge).toContain('{direction}');
    });
    it('en', () => {
        expect(en.rankingBadge).toContain('{formula}');
        expect(en.rankingBadge).toContain('{direction}');
    });
});
