import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { extname, join } from 'node:path';
import test from 'node:test';

/**
 * Guard: un enlace DENTRO de una frase (un <p> con más texto) va subrayado
 * siempre, no solo al pasar el ratón (WCAG 2.2 SC 1.4.1, uso del color; regla
 * axe-core link-in-text-block, seria). El teal de los enlaces sobre la tinta
 * gris de la app da 1,7:1 frente al texto que lo rodea (mínimo 3:1), así que
 * sin subrayado en el móvil el enlace no se distingue (no hay hover).
 *
 * Origen: barrido axe sobre un build de producción (r5-a11y, 12-nov-2026) de
 * los recorridos principales (inicio/watchlist, pestañas de la ficha, Informe,
 * cartera) a 390 y 1440 px: «Ver todos los políticos» en Seguimiento. El mismo
 * patrón estaba en otros 8 enlaces de esos recorridos que solo se pintan con
 * otros datos (insiders con formulario, auditoría de fuentes, filtros vacíos,
 * previsión de la cartera, inteligencia de cartera). tests/unit/accessibility/
 * InlineLinkUnderline.test.ts cubría un enlace concreto; esto cubre el patrón.
 *
 * Un enlace que es TODO el contenido del párrafo no es «enlace en un bloque de
 * texto» y no se exige. El token exigido es `underline` exacto: `hover:underline`
 * o `underline-offset-2` no cuentan.
 *
 * Ejecución: node --experimental-strip-types --test scripts/inline-link-underline-guard.test.ts
 */

const ROOTS = [
    'components/research', 'components/watchlist', 'components/portfolio',
    'app/(root)/research', 'app/(root)/watchlist', 'app/(root)/portfolio', 'app/(root)/inicio',
    'components/PersonalizedOverview.tsx', 'components/HomeAttention.tsx',
];
/** Excepciones con motivo. */
const ALLOW: Record<string, string> = {
    // Generación de tesis (LLM): sin cambios de código mientras no haya cuota (Nico, 11-nov).
    'components/research/ThesisGenerateButton.tsx': 'función con LLM congelada',
    // El enlace es todo el párrafo (titular original), con un ternario que el detector lee como texto.
    'components/research/ExternalNewsHeadline.tsx': 'el enlace es todo el párrafo',
};

const walk = (path: string, out: string[] = []): string[] => {
    if (statSync(path).isFile()) return extname(path) === '.tsx' ? [...out, path] : out;
    for (const entry of readdirSync(path)) {
        const full = join(path, entry);
        if (statSync(full).isDirectory()) walk(full, out);
        else if (extname(full) === '.tsx' && !/\.(test|spec)\.tsx$/.test(full)) out.push(full);
    }
    return out;
};

/** Enlaces de un <p> con texto propio cuyo className no lleva el token `underline`. */
export function inlineLinksWithoutUnderline(source: string): string[] {
    const found: string[] = [];
    for (const paragraph of source.matchAll(/<p\b[^>]*>([\s\S]*?)<\/p>/g)) {
        const inner = paragraph[1];
        const outside = inner.replace(/<(Link|a)\b[\s\S]*?<\/\1>/g, '').replace(/<[^>]+>/g, '');
        if (!/[A-Za-zÁÉÍÓÚáéíóúñ]|\{t\(|\{ti\(/.test(outside)) continue;
        for (const link of inner.matchAll(/<(Link|a)\b([^>]*)>/g)) {
            const cls = /className="([^"]*)"/.exec(link[2])?.[1] ?? '';
            const tokens = cls.split(/\s+/).filter(Boolean);
            if (tokens.includes('underline') || tokens.includes('no-underline')) continue;
            found.push(`<${link[1]} className="${cls}">`);
        }
    }
    return found;
}

test('detector: rechaza el enlace que solo subraya al hover y acepta el subrayado fijo', () => {
    assert.deepEqual(inlineLinksWithoutUnderline('<p>Texto <a className="text-teal-300 hover:underline underline-offset-2" href="/x">ver</a></p>'), [
        '<a className="text-teal-300 hover:underline underline-offset-2">',
    ]);
    assert.deepEqual(inlineLinksWithoutUnderline('<p>{t(\'k\')} <Link className="text-teal-300" href="/x">ver</Link></p>'), ['<Link className="text-teal-300">']);
    assert.deepEqual(inlineLinksWithoutUnderline('<p>Texto <a className="text-teal-300 underline underline-offset-2" href="/x">ver</a></p>'), []);
    // El enlace que ocupa todo el párrafo no es un enlace dentro de texto.
    assert.deepEqual(inlineLinksWithoutUnderline('<p className="m-0"><Link className="text-teal-300" href="/x">{t(\'k\')}</Link></p>'), []);
});

test('los enlaces dentro de frases de los recorridos principales van subrayados siempre', () => {
    const offenders: string[] = [];
    for (const root of ROOTS) {
        for (const file of walk(root)) {
            const rel = file.split('\\').join('/');
            if (rel in ALLOW) continue;
            for (const hit of inlineLinksWithoutUnderline(readFileSync(file, 'utf8'))) offenders.push(`${rel}: ${hit}`);
        }
    }
    assert.deepEqual(offenders, [], `enlaces en texto sin el token \`underline\`:\n${offenders.join('\n')}`);
});
