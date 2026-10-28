/**
 * Guard de rendimiento móvil: react-markdown + remark-gfm (~47 KB gzip con
 * micromark/hast) no pueden viajar en el bundle inicial de /research ni de
 * /research/[ticker]. El visor de markdown se carga diferido en los dos
 * puntos que lo pintan en esas rutas (memorando paginado y documento de
 * trabajo generado), como ya hacía el Cerebro global con su respuesta.
 *
 * Medida (build local, main 3f9631d8): /research cargaba 173,3 KB gzip de
 * JS inicial y /research/[ticker] 200,5 KB; ~47 KB gz de cada uno eran los
 * chunks de micromark/hast de react-markdown.
 *
 * Ejecución: node --experimental-strip-types --test scripts/markdown-lazy-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const pager = readFileSync('components/research/ThesisMarkdownPager.tsx', 'utf8');
const workProduct = readFileSync('components/work-products/WorkProductButton.tsx', 'utf8');

const STATIC_THESIS_MARKDOWN = /^import\s+ThesisMarkdown\s+from\s+['"]@\/components\/research\/ThesisMarkdown['"]/m;

describe('markdown: visor diferido en research', () => {
    it('el paginador del memorando carga ThesisMarkdown con dynamic()', () => {
        assert.ok(!STATIC_THESIS_MARKDOWN.test(pager), 'ThesisMarkdownPager no debe importar ThesisMarkdown en estático');
        assert.match(pager, /dynamic\(\(\) => import\('@\/components\/research\/ThesisMarkdown'\)/);
    });

    it('el documento de trabajo carga ThesisMarkdown con dynamic()', () => {
        assert.ok(!STATIC_THESIS_MARKDOWN.test(workProduct), 'WorkProductButton no debe importar ThesisMarkdown en estático');
        assert.match(workProduct, /dynamic\(\(\) => import\('@\/components\/research\/ThesisMarkdown'\)/);
    });

    it('ambos declaran un estado de carga (nunca un hueco en blanco)', () => {
        assert.match(pager, /loading:\s*\(\)\s*=>/);
        assert.match(workProduct, /loading:\s*\(\)\s*=>/);
    });
});
