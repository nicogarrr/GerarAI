import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, normalize } from 'node:path';
import { test } from 'node:test';

/** Contrato imports <-> contexto Docker: `npm run build` typechequea
 *  tests/unit/ y playwright.config.ts (el tsconfig compila tambien los tests), asi que
 *  cualquier helper de e2e/ que importen debe entrar en el contexto de build
 *  de frontend-prod o el `COPY . .` + `next build` falla con TS2307. Este
 *  guard simula .dockerignore (semantica Go filepath.Match, la ultima regla
 *  que casa decide, `!` re-incluye, excluir un directorio excluye su
 *  contenido) sobre cada import que resuelve dentro de e2e/. */

const IMPORT_RE = /(?:import|export)[^'"]*?from\s+['"](\.[^'"]+)['"]|import\(\s*['"](\.[^'"]+)['"]\s*\)/g;

function* sources(dir: string): Generator<string> {
    for (const entry of readdirSync(dir)) {
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) {
            yield* sources(full);
        } else if (/\.tsx?$/.test(entry)) {
            yield full;
        }
    }
}

/** pattern de .dockerignore -> RegExp de ruta completa (sin * cruzando /,
 *  ** cruzando; barra final = el directorio y sus descendientes). */
function ruleToRe(rawPattern: string): RegExp {
    let pattern = rawPattern;
    if (pattern.endsWith('/')) pattern = pattern.slice(0, -1);
    const body = pattern
        .replace(/[.+^${}()|[\]\\]/g, '\\$&')
        .replace(/\*\*/g, ' ')
        .replace(/\*/g, '[^/]*')
        .replace(/ /g, '.*');
    return new RegExp(`^${body}(/.*)?$`);
}

/** Decision final de .dockerignore para una ruta: la ultima regla que casa. */
interface IgnoreRule { include: boolean; re: RegExp }

function dockerContextIncludes(path: string, rules: IgnoreRule[]): boolean {
    let included = true;
    for (const rule of rules) {
        if (rule.re.test(path)) included = rule.include;
    }
    return included;
}

test('todo import que resuelve dentro de e2e/ entra en el contexto de build (TS2307)', () => {
    const rules = readFileSync('.dockerignore', 'utf8')
        .split('\n')
        .map((l) => l.trim())
        .filter((l) => l && !l.startsWith('#'))
        .map((l) => {
            const include = l.startsWith('!');
            const pattern = include ? l.slice(1) : l;
            return { include, re: ruleToRe(pattern) };
        });

    const files = [...sources('tests/unit'), 'playwright.config.ts'];
    const missing = [];
    for (const file of files) {
        const src = readFileSync(file, 'utf8');
        for (const match of src.matchAll(IMPORT_RE)) {
            const spec = match[1] ?? match[2];
            const resolved = normalize(join(dirname(file), spec));
            for (const ext of ['', '.ts', '.tsx', '/index.ts']) {
                const candidate = resolved + ext;
                if (candidate.startsWith('e2e/')) {
                    try {
                        statSync(candidate);
                        if (!dockerContextIncludes(candidate, rules)) {
                            missing.push(`${file} importa ${spec} -> ${candidate} excluido por .dockerignore`);
                        }
                        break;
                    } catch { /* la extension no es */ }
                }
            }
        }
    }
    assert.deepEqual(missing, [],
        'imports de e2e/ fuera del contexto Docker (el build de frontend-prod fallaria con TS2307):\n' + missing.join('\n'));
});

test('el guard muerde: un helper e2e excluido se detecta (caso negativo)', () => {
    const rules: IgnoreRule[] = [
        { include: false, re: ruleToRe('e2e/*') },
        { include: true, re: ruleToRe('e2e/user-flows/') },
        { include: false, re: ruleToRe('e2e/user-flows/*') },
        { include: true, re: ruleToRe('e2e/user-flows/warmup-routes.ts') },
    ];
    assert.equal(dockerContextIncludes('e2e/user-flows/warmup-routes.ts', rules), true);
    assert.equal(dockerContextIncludes('e2e/user-flows/sign-in-account.ts', rules), false);
    assert.equal(dockerContextIncludes('e2e/ficha.spec.ts', rules), false);
});
