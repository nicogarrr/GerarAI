import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';

// Un Server Component que importa de un módulo 'use client' recibe una
// referencia de cliente: solo sirve para pintar el componente. Un valor
// (constante, función) importado así revienta en el servidor; #2971 dejó
// /inversores/<slug> en 500 con «VIEWS.some is not a function».
const ROOT = path.resolve(__dirname, '../../..');
const ENTRY = /^(page|layout|template|not-found|default)\.tsx?$/;

function walk(dir: string, out: string[] = []): string[] {
    for (const name of readdirSync(dir)) {
        const full = path.join(dir, name);
        if (statSync(full).isDirectory()) walk(full, out);
        else if (ENTRY.test(name)) out.push(full);
    }
    return out;
}

const isClient = (src: string) => /^\s*(?:\/\/[^\n]*\n|\/\*[\s\S]*?\*\/\s*)*['"]use client['"]/.test(src);

function resolveImport(from: string, spec: string): string | null {
    let base: string;
    if (spec.startsWith('@/')) base = path.join(ROOT, spec.slice(2));
    else if (spec.startsWith('.')) base = path.resolve(path.dirname(from), spec);
    else return null;
    for (const candidate of [base, `${base}.tsx`, `${base}.ts`, path.join(base, 'index.tsx'), path.join(base, 'index.ts')]) {
        if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
    }
    return null;
}

export function clientValueImports(file: string): string[] {
    const src = readFileSync(file, 'utf8');
    if (isClient(src)) return [];
    const problems: string[] = [];
    for (const match of src.matchAll(/^import\s+(?!type\b)\{([^}]*)\}\s+from\s+['"]([^'"]+)['"]/gm)) {
        const target = resolveImport(file, match[2]);
        if (!target || !isClient(readFileSync(target, 'utf8'))) continue;
        for (const raw of match[1].split(',')) {
            const name = raw.trim().replace(/^type\s+.*/, '').split(/\s+as\s+/)[0];
            // Componentes en PascalCase (InvestorViewSelector); todo lo demás es un valor.
            if (name && !/^[A-Z][a-z0-9]/.test(name)) problems.push(`${path.relative(ROOT, file)}: ${name} de ${match[2]}`);
        }
    }
    return problems;
}

describe('frontera servidor/cliente en páginas', () => {
    it('ninguna página de servidor importa valores de un módulo «use client»', () => {
        const problems = walk(path.join(ROOT, 'app')).flatMap(clientValueImports);
        expect(problems).toEqual([]);
    });
});
