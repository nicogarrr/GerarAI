/**
 * Guard de cortes silenciosos: toda lista truncada declara cuántos elementos
 * muestra de cuántos hay ("Se muestran N de M"), y «Lo que debe cumplirse»
 * se muestra completo. Una lista cortada sin aviso aparenta ser el total.
 * Ejecución: node --experimental-strip-types --test scripts/silent-cuts-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const tickerPage = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const sourcesPage = readFileSync('app/(root)/research/sources/page.tsx', 'utf8');
const panels = readFileSync('components/research/FundamentalModelPanels.tsx', 'utf8');

describe('cortes de lista declarados', () => {
    it('operaciones insider de un Form 4: 6 de N declarado', () => {
        assert.match(tickerPage, /Se muestran 6 de \{formatNumber\(filing\.transactions\.length/);
    });
    it('auditorías por empresa: última visible, historial plegado y 100 de N declarado', () => {
        assert.match(tickerPage, /Se muestran 100 de \{formatNumber\(audits\.length/);
        assert.match(tickerPage, /la última y hasta 99 anteriores/);
        assert.match(tickerPage, /renderAudit\(ordered\[0\]\)/);
        assert.match(tickerPage, /previous = ordered\.slice\(1, 100\)/);
        assert.match(tickerPage, /<details[\s\S]*previous\.map\(renderAudit\)/);
    });
    it('auditorías en /research/sources: 8 de N declarado', () => {
        assert.match(sourcesPage, /Se muestran 8 de \{formatNumber\(audits\.length/);
    });
    it('«Lo que debe cumplirse» se muestra completo, sin corte', () => {
        assert.ok(!panels.includes('what_must_be_true.slice('), 'corte silencioso en lo que debe cumplirse');
    });
    it('comparaciones y previsiones: todas accesibles por paginación con total', () => {
        const list = readFileSync('components/research/ExpectationsList.tsx', 'utf8');
        const pager = readFileSync('components/research/Pager.tsx', 'utf8');
        assert.match(list, /paginate\(main, page, PAGE\)/);
        assert.match(list, /total=\{main\.length\}/);
        assert.match(list, /total=\{pending\.length\}/);
        // «Página x de y» va en su propio span (huérfanos 390px): el contrato es paginación con total, no la adyacencia literal.
        assert.match(pager, /Página \{page\} de \{pages\}/);
        assert.match(pager, /· \{total\} \{label\}/);
    });
});
