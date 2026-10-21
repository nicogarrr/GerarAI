import { readFileSync } from 'node:fs';
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: extensión explícita para node --experimental-strip-types.
import { splitMemoPages } from '../lib/research/memo-pages.ts';

// El API sustituye thesis_markdown por "# Valoración no disponible" + motivo
// cuando la valoración usa inputs inferidos (schemas/api.py,
// _withhold_inferred_valuation). Sin encabezados `## `, splitMemoPages
// devolvía [] y el paginador no pintaba NADA bajo «Memorando completo»:
// el motivo de la retención desaparecía de la UI (QA 22-oct-2026).
const WITHHELD = '# Valoración no disponible\n\nValoración no disponible: faltan ingresos modelados con fuente. El modelo solo se podía calcular con un supuesto no verificado, así que no se publica ningún valor por acción.\n';

describe('memo-pages: respaldo sin secciones `## `', () => {
    it('markdown de retención rinde UNA página con el motivo íntegro', () => {
        const pages = splitMemoPages(WITHHELD);
        assert.equal(pages.length, 1);
        assert.equal(pages[0].title, 'Valoración no disponible');
        assert.match(pages[0].body, /faltan ingresos modelados con fuente/);
        assert.match(pages[0].body, /no se publica ningún valor por acción/);
    });
    it('texto sin encabezados ni H1 rinde una página "Memo" con todo el contenido', () => {
        const pages = splitMemoPages('Párrafo suelto sin encabezados.\n\nOtro párrafo.');
        assert.equal(pages.length, 1);
        assert.equal(pages[0].title, 'Memo');
        assert.match(pages[0].body, /Párrafo suelto/);
        assert.match(pages[0].body, /Otro párrafo/);
    });
    it('markdown vacío o solo blanco sigue devolviendo [] (nada que mostrar)', () => {
        assert.deepEqual(splitMemoPages(''), []);
        assert.deepEqual(splitMemoPages('   \n \n'), []);
    });
    it('memo normal con `## ` NO toca el respaldo: mismas páginas de siempre', () => {
        const normal = '# Tesis ASML\n\nintro\n\n## 1. Resumen ejecutivo\n\ntexto resumen\n\n## 2. Valoración\n\ntexto valoración\n';
        const pages = splitMemoPages(normal);
        assert.deepEqual(pages.map((p) => p.title), ['Resumen ejecutivo', 'Valoración']);
        assert.match(pages[0].body, /intro/);
    });
    it('secciones `## ` con cuerpo no caen en la página única', () => {
        const pages = splitMemoPages('## A\n\ncontenido A\n');
        assert.equal(pages.length, 1);
        assert.equal(pages[0].title, 'A');
        assert.match(pages[0].body, /contenido A/);
    });
    it('wiring: ThesisMemo sigue pasando thesis_markdown por splitMemoPages', () => {
        const memo = readFileSync('components/research/ThesisMemo.tsx', 'utf8');
        assert.match(memo, /splitMemoPages\(thesis\.thesis_markdown\)/);
    });
});
