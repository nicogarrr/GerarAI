/**
 * Guard de contraste del texto (WCAG 2.2 SC 1.4.3, 4,5:1 en texto normal).
 *
 * Por qué: en `app/globals.css` la escala de grises NO es la de Tailwind:
 * gray-600 (#3f3f46) y gray-700 (#27272a) son colores de BORDE. Como texto
 * sobre el fondo de la app dan 1,9:1 y 1,3:1: el texto existe pero no se lee
 * (el propio comentario del @theme dice «NO usar como texto (1.7:1)»).
 * `slate-500` (#64748b, el de Tailwind) da 4,2:1 sobre el fondo y 3,7:1 sobre
 * surface-2, por debajo de 4,5:1. Las iniciales del avatar en teal-900 sobre
 * teal-500 daban 2,5:1.
 *
 * Regla: en `app/` y `components/` no se usa `text-gray-600`, `text-gray-700`,
 * `text-slate-500` ni `placeholder:text-gray-600/700` como color de texto.
 * Se usa `text-gray-500` (7,7:1) o `text-slate-400` (7,7:1).
 *
 * Excepciones legitimas, sin allowlist: variantes de estado deshabilitado
 * (`disabled:`, `aria-disabled:`, `group-disabled:`), `print:`, y elementos
 * con `aria-hidden` o `aria-disabled` en la misma linea (WCAG exime el texto
 * de controles inactivos y lo puramente decorativo). Las constantes de clase
 * que solo se aplican a paginadores `aria-disabled` van en la allowlist.
 *
 * Ejecución: node --experimental-strip-types --test scripts/text-contrast-token-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';

const ROOTS = ['app', 'components'];

/** Token de texto de bajo contraste SIN variante delante (hover:, md:, ...). */
const LOW_CONTRAST = /(?<![\w:-])(?:placeholder:)?text-(?:gray-(?:600|700)|slate-500)(?![\w/-])/g;
const EXEMPT_LINE = /aria-hidden|aria-disabled/;

/** Constantes de clase usadas solo en `<span aria-disabled="true">`. */
const ALLOWLIST: readonly { file: string; why: string }[] = [
    { file: 'app/(root)/inversores/_components/PaginationNav.tsx', why: '`offClass`: solo en el paginador aria-disabled (texto de control inactivo, exento de 1.4.3).' },
    { file: 'components/research/NewsEventsFlow.tsx', why: '`PAGER_OFF`: solo en el paginador aria-disabled (texto de control inactivo, exento de 1.4.3).' },
];

function sourceFiles(root: string, out: string[] = []): string[] {
    for (const entry of readdirSync(root, { withFileTypes: true })) {
        if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
        const full = path.join(root, entry.name);
        if (entry.isDirectory()) sourceFiles(full, out);
        else if (/\.tsx?$/.test(entry.name) && !/\.(test|spec)\.tsx?$/.test(entry.name)) out.push(full);
    }
    return out;
}

export function lowContrastHits(source: string): { line: number; token: string }[] {
    const hits: { line: number; token: string }[] = [];
    source.split('\n').forEach((text, index) => {
        if (EXEMPT_LINE.test(text)) return;
        for (const match of text.matchAll(LOW_CONTRAST)) hits.push({ line: index + 1, token: match[0] });
        if (/\bbg-teal-500\b/.test(text) && /(?<![\w:-])text-teal-900\b/.test(text)) hits.push({ line: index + 1, token: 'text-teal-900 sobre bg-teal-500' });
    });
    return hits;
}

describe('text-contrast-token-guard', () => {
    it('detecta los tokens de bajo contraste y respeta las exenciones', () => {
        assert.deepEqual(lowContrastHits('<p className="text-xs text-gray-600">Hola</p>').map((h) => h.token), ['text-gray-600']);
        assert.deepEqual(lowContrastHits('<input className="placeholder:text-gray-700" />').map((h) => h.token), ['placeholder:text-gray-700']);
        assert.deepEqual(lowContrastHits('<p className="text-slate-500">x</p>').map((h) => h.token), ['text-slate-500']);
        assert.deepEqual(lowContrastHits('<b className="bg-teal-500 text-teal-900">NG</b>').length, 1);
        assert.deepEqual(lowContrastHits('<button className="text-teal-300 disabled:text-gray-600">x</button>'), []);
        assert.deepEqual(lowContrastHits('<Icon aria-hidden="true" className="text-gray-600" />'), []);
        assert.deepEqual(lowContrastHits('<span aria-disabled="true" className="text-gray-600">Anterior</span>'), []);
        assert.deepEqual(lowContrastHits('<p className="text-gray-500 decoration-gray-600 border-gray-600">x</p>'), []);
        assert.deepEqual(lowContrastHits('<p className="text-gray-600/50">x</p>'), []);
    });

    it('app/ y components/ no usan texto de bajo contraste', () => {
        const allowed = new Set(ALLOWLIST.map((entry) => entry.file));
        const offenders: string[] = [];
        for (const root of ROOTS) {
            for (const file of sourceFiles(root)) {
                const rel = file.split(path.sep).join('/');
                if (allowed.has(rel)) continue;
                for (const hit of lowContrastHits(readFileSync(file, 'utf8'))) offenders.push(`${rel}:${hit.line} ${hit.token}`);
            }
        }
        assert.deepEqual(offenders, [], `Texto por debajo de 4,5:1. Usa text-gray-500 / text-slate-400:\n${offenders.join('\n')}`);
    });
});
