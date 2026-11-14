import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

/** El script de captura pre-hidratacion (lib/early-open) SOLO puede servirse
 *  desde el layout raiz (app/layout.tsx). React NUNCA ejecuta un <script> que
 *  aparece al renderizar en cliente (error "Encountered a script tag" en dev,
 *  omision silenciosa en prod): un layout de segmento como app/(root)/layout
 *  se monta en cliente al navegar desde sign-in, y ahi el script se perdia y
 *  ensuciaba la consola. El layout raiz no se remonta en navegaciones
 *  cliente, asi que el script llega siempre en el HTML inicial, que es donde
 *  corre. */

// Insensible a mayúsculas: un <SCRIPT> mayúscula es igual de omitido por
// React (CodeQL js/bad-tag-filter sobre la versión sensible a mayúsculas).
const INLINE_SCRIPT_RE = /<script[\s>]/i;

function* layouts(dir: string): Generator<string> {
    for (const entry of readdirSync(dir)) {
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) {
            yield* layouts(full);
        } else if (entry === 'layout.tsx') {
            yield full;
        }
    }
}

test('la captura pre-hidratacion se sirve desde el layout raiz, con nonce', () => {
    const root = readFileSync('app/layout.tsx', 'utf8');
    assert.match(root, /import \{ EARLY_OPEN_CAPTURE_JS \} from ["']@\/lib\/early-open["']/);
    assert.match(root, /<script nonce=\{nonce\} dangerouslySetInnerHTML=\{\{ __html: EARLY_OPEN_CAPTURE_JS \}\} \/>/);
    // Antes de {children}: el script corre antes que cualquier gatillo.
    assert.ok(
        root.indexOf('EARLY_OPEN_CAPTURE_JS }} />') < root.indexOf('{children}'),
        'el script debe pintarse antes que los gatillos',
    );
});

test('ningun layout de segmento renderiza un <script> inline (React lo omitiría en cliente)', () => {
    const offenders = [];
    for (const file of layouts('app')) {
        if (file === join('app', 'layout.tsx')) continue;
        const src = readFileSync(file, 'utf8');
        if (INLINE_SCRIPT_RE.test(src) && /dangerouslySetInnerHTML/.test(src)) offenders.push(file);
    }
    assert.deepEqual(offenders, [],
        'un <script> inline en un layout de segmento se pierde al montarlo React en cliente:\n' + offenders.join('\n'));
});

test('el detector de <script> inline también casa <SCRIPT> en mayúsculas', () => {
    assert.match('<SCRIPT nonce="x">y</SCRIPT>', INLINE_SCRIPT_RE);
    assert.match('<script\nnonce="x">y</script>', INLINE_SCRIPT_RE);
    assert.doesNotMatch('<description>script</description>', INLINE_SCRIPT_RE);
});
