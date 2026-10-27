/**
 * Resumen de cobertura del frontend: une lo que ejecutan los tests de
 * comportamiento (Vitest, `coverage/frontend/lcov.info`) y los guards
 * `node --test` (`coverage/frontend/guards.lcov`, ver `run-guards.mjs --coverage`).
 *
 * El DENOMINADOR es el informe de Vitest, que incluye TODOS los ficheros de
 * lib/, components/ y middleware.ts (también los que ningún test importa,
 * a 0 %). La cobertura nativa de node:test solo conoce los ficheros que algún
 * guard llegó a cargar, así que por sí sola daría un porcentaje inflado: aquí
 * solo aporta qué líneas de ese denominador se ejecutaron.
 *
 * Una línea cuenta como cubierta si cualquiera de los dos runners la ejecutó.
 * Es informativo (no hunde CI): el trinquete que bloquea son los `thresholds`
 * de vitest.config.mts. Docs: docs/FRONTEND_TESTS.md.
 *
 * Uso: node scripts/frontend-coverage-summary.mjs [--markdown]
 */
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const VITEST_LCOV = path.join(REPO_ROOT, 'coverage', 'frontend', 'lcov.info');
const GUARDS_LCOV = path.join(REPO_ROOT, 'coverage', 'frontend', 'guards.lcov');

/** LCOV → Map<ruta relativa al repo, Map<línea, hits>> */
export function parseLcov(text, root = REPO_ROOT) {
  const files = new Map();
  let current = null;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (line.startsWith('SF:')) {
      const sf = line.slice(3);
      const rel = (path.isAbsolute(sf) ? path.relative(root, sf) : sf).split(path.sep).join('/');
      current = files.get(rel) ?? new Map();
      files.set(rel, current);
    } else if (line.startsWith('DA:') && current) {
      const [ln, hits] = line.slice(3).split(',');
      const n = Number(ln);
      current.set(n, Math.max(current.get(n) ?? 0, Number(hits) || 0));
    } else if (line === 'end_of_record') {
      current = null;
    }
  }
  return files;
}

function areaOf(file) {
  if (file.startsWith('lib/')) return 'lib/';
  if (file.startsWith('components/')) return 'components/';
  return file;
}

/** Cuenta líneas cubiertas por área con el denominador de Vitest. */
export function summarize(vitest, guards) {
  const areas = new Map();
  const bump = (key, field) => {
    const a = areas.get(key) ?? { total: 0, vitest: 0, guards: 0, union: 0, files: 0, filesTouched: 0 };
    a[field] += 1;
    areas.set(key, a);
  };
  for (const [file, lines] of vitest) {
    const g = guards.get(file);
    let touched = false;
    for (const [ln, hits] of lines) {
      const byVitest = hits > 0;
      const byGuards = (g?.get(ln) ?? 0) > 0;
      for (const key of [areaOf(file), 'total']) {
        bump(key, 'total');
        if (byVitest) bump(key, 'vitest');
        if (byGuards) bump(key, 'guards');
        if (byVitest || byGuards) bump(key, 'union');
      }
      touched ||= byVitest || byGuards;
    }
    for (const key of [areaOf(file), 'total']) {
      bump(key, 'files');
      if (touched) bump(key, 'filesTouched');
    }
  }
  return areas;
}

const pct = (n, d) => (d === 0 ? 'N/D' : `${((100 * n) / d).toFixed(2).replace('.', ',')} %`);

function main() {
  if (!existsSync(VITEST_LCOV)) {
    console.error(`frontend-coverage-summary: falta ${path.relative(REPO_ROOT, VITEST_LCOV)} (ejecuta antes npm run test:coverage).`);
    process.exit(1);
  }
  const vitest = parseLcov(readFileSync(VITEST_LCOV, 'utf8'));
  const guards = existsSync(GUARDS_LCOV) ? parseLcov(readFileSync(GUARDS_LCOV, 'utf8')) : new Map();
  if (guards.size === 0) console.error('frontend-coverage-summary: sin guards.lcov; solo se cuenta Vitest.');
  const areas = summarize(vitest, guards);
  const order = ['lib/', 'components/', 'middleware.ts', 'total'].filter((k) => areas.has(k));
  const rows = order.map((k) => {
    const a = areas.get(k);
    return [k === 'total' ? '**Total**' : `\`${k}\``, `${a.filesTouched}/${a.files}`, String(a.total), pct(a.vitest, a.total), pct(a.guards, a.total), pct(a.union, a.total)];
  });
  const out = [
    '### Cobertura del frontend (líneas)',
    '',
    '| Ámbito | Ficheros ejecutados | Líneas | Vitest (comportamiento) | Guards node:test | Unión |',
    '|---|---|---|---|---|---|',
    ...rows.map((r) => `| ${r.join(' | ')} |`),
    '',
    'Denominador: todos los ficheros de lib/, components/ y middleware.ts (los no importados por ningún test cuentan a 0 %). Los guards que solo leen el código con regex no ejecutan nada y no suman.',
  ].join('\n');
  console.log(out);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
