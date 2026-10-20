import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

/**
 * Un server component no puede LLAMAR funciones exportadas por un módulo
 * 'use client' (React #441, "No se pudo completar la operación"): solo puede
 * renderizar sus componentes (export default o PascalCase) o importar tipos.
 * Los helpers puros van a lib/ sin 'use client'.
 */
const ROOTS = ['app', 'components'];
const isClient = (src: string) => /^\s*(?:\/\*[\s\S]*?\*\/\s*|\/\/.*\n\s*)*['"]use client['"]/.test(src);

function walk(dir: string, out: string[] = []): string[] {
    for (const name of readdirSync(dir)) {
        const full = join(dir, name);
        if (statSync(full).isDirectory()) walk(full, out);
        else if (/\.tsx?$/.test(name) && !/\.test\./.test(name)) out.push(full);
    }
    return out;
}

function resolveModule(from: string, spec: string): string | null {
    const base = spec.startsWith('@/') ? resolve(spec.slice(2)) : spec.startsWith('.') ? resolve(dirname(from), spec) : null;
    if (!base) return null;
    for (const candidate of [`${base}.tsx`, `${base}.ts`, join(base, 'index.tsx'), join(base, 'index.ts')]) {
        if (existsSync(candidate)) return candidate;
    }
    return null;
}

describe('server components no importan funciones de módulos use client', () => {
    it('solo componentes (default o PascalCase) o tipos', () => {
        const violations: string[] = [];
        for (const file of ROOTS.flatMap((root) => walk(root))) {
            const src = readFileSync(file, 'utf8');
            if (isClient(src)) continue;
            for (const match of src.matchAll(/import\s+(?!type\b)([^;]*?)\s+from\s+['"]([^'"]+)['"]/g)) {
                const target = resolveModule(file, match[2]);
                if (!target || !isClient(readFileSync(target, 'utf8'))) continue;
                const named = /\{([^}]*)\}/.exec(match[1])?.[1] ?? '';
                for (const raw of named.split(',')) {
                    const item = raw.trim();
                    if (!item || item.startsWith('type ')) continue;
                    const name = item.split(/\s+as\s+/)[0].trim();
                    if (!/^[A-Z]/.test(name)) violations.push(`${file}: ${name} desde ${match[2]}`);
                }
            }
        }
        assert.deepEqual(violations, []);
    });
});

describe('memo-pages es módulo de servidor', () => {
    it('no es use client y parte el memo por ## ', async () => {
        const src = readFileSync('lib/research/memo-pages.ts', 'utf8');
        assert.ok(!isClient(src));
        // @ts-expect-error TS5097: extensión explícita para node --experimental-strip-types.
        const { splitMemoPages } = await import('../lib/research/memo-pages.ts');
        const pages = splitMemoPages('# Titulo\n\n## 1. Uno\ntexto\n\n## 2. Dos\notro');
        // El paginador numera las opciones; el titulo llega sin numeracion
        // propia (antes se duplicaba: "1. 1. Uno").
        assert.deepEqual(pages.map((p: { title: string }) => p.title), ['Uno', 'Dos']);
    });
});
