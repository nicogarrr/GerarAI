import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';

// Quien reutiliza `markdownComponents` de ThesisMarkdown (Biblioteca →
// fragmentos, respuestas de la biblioteca en el Cerebro) pinta texto que no
// controla: enlaces, tokens sin espacios, tablas GFM. Si el contenedor no puede
// encoger (min-w-0) ni partir palabras, a 390 px la tarjeta se ensancha más
// que la pantalla y el overflow-x-clip del <main> la recorta sin forma de
// leerla (el scrollWidth de la página no cambia, así que los specs de overflow
// no lo veían). El e2e e2e/mobile-clipped-content.spec.ts lo mide en el
// navegador; esta guarda lo fija en el código.
const ROOTS = ['app', 'components'];
const WRAP = /\[overflow-wrap:anywhere\]|\bwrap-anywhere\b|\bbreak-words\b|\bbreak-all\b/;

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (full.endsWith('.tsx')) out.push(full);
  }
  return out;
}

const consumers = ROOTS.flatMap((root) => walk(root)).filter((file) => {
  const text = readFileSync(file, 'utf8');
  return /import\s*\{[^}]*\bmarkdownComponents\b[^}]*\}\s*from\s*['"]@\/components\/research\/ThesisMarkdown['"]/.test(text);
});

test('hay consumidores de markdownComponents (si no, revisa esta guarda)', () => {
  assert.ok(consumers.length > 0);
});

test('cada <ReactMarkdown components={markdownComponents}> vive en un contenedor que encoge y parte palabras', () => {
  const problems: string[] = [];
  for (const file of consumers) {
    const text = readFileSync(file, 'utf8');
    const re = /<ReactMarkdown\b[^>]*components=\{markdownComponents\}/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text))) {
      const before = text.slice(Math.max(0, m.index - 600), m.index);
      const classes = [...before.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/g)];
      const last = classes.at(-1);
      const cls = last ? (last[1] ?? last[2] ?? '') : '';
      if (!/\bmin-w-0\b/.test(cls) || !WRAP.test(cls)) {
        problems.push(`${file}: contenedor «${cls || '(sin className)'}» sin min-w-0 y corte de palabra`);
      }
    }
  }
  assert.deepEqual(problems, []);
});
