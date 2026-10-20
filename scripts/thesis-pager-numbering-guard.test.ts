/**
 * Guard: el selector del memorando numera las opciones ({i + 1}.), así que
 * splitMemoPages limpia la numeración propia del encabezado. Antes salía
 * duplicada: "1. 1. Resumen ejecutivo".
 * Ejecución: node --experimental-strip-types --test scripts/thesis-pager-numbering-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { splitMemoPages } from '../lib/research/memo-pages.ts';

const pager = readFileSync('components/research/ThesisMarkdownPager.tsx', 'utf8');

describe('selector del memorando: numeración una sola vez', () => {
    it('el paginador numera las opciones', () => {
        assert.match(pager, /\{i \+ 1\}\. \{entry\.title\}/);
    });

    it('los títulos llegan sin numeración propia', () => {
        const pages = splitMemoPages('# Memo\n\n## 1. Resumen ejecutivo\n\nTexto A.\n\n## 2. Tesis\n\nTexto B.\n');
        assert.deepEqual(pages.map((page) => page.title), ['Resumen ejecutivo', 'Tesis']);
    });

    it('la numeración se conserva en el cuerpo de la sección', () => {
        const [first] = splitMemoPages('# Memo\n\n## 1. Resumen ejecutivo\n\nTexto A.\n');
        assert.match(first.body, /## 1\. Resumen ejecutivo/);
    });

    it('un decimal no es una enumeración y no se corta', () => {
        const [page] = splitMemoPages('## 1.5 Dividendos\n\nTexto.\n');
        assert.equal(page.title, '1.5 Dividendos');
    });
});
