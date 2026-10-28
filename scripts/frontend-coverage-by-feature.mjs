/**
 * Cobertura del frontend POR FUNCIONALIDAD (informativo, nunca falla).
 *
 * `coverage/frontend/coverage-summary.json` (Vitest, json-summary) da el % por
 * fichero; `frontend-coverage-summary.mjs` lo agrupa por lib/ vs components/.
 * Ninguno dice si una funcionalidad de producto (impuestos, DCA, cartera,
 * auth...) está bien probada. Este script agrupa los ficheros por
 * funcionalidad y lista, para cada una, líneas/ramas cubiertas y los ficheros
 * con más líneas sin cubrir.
 *
 * Uso: node scripts/frontend-coverage-by-feature.mjs [--markdown] [--json out.json] [--top N]
 * Sale SIEMPRE con 0: es un informe, no un gate (el trinquete es vitest.config.mts).
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SUMMARY = path.join(REPO_ROOT, 'coverage', 'frontend', 'coverage-summary.json');

/** Orden = prioridad: el primer patrón que encaja se queda el fichero. */
export const FEATURES = [
  ['impuestos (IRPF/720)', /^(lib|components)\/taxes\/|^lib\/actions\/taxes/],
  ['DCA', /^lib\/dca\/|\/[Dd]ca[A-Z_-]|^components\/.*\/dca|^lib\/actions\/dca/],
  ['cartera/tearsheet', /^lib\/portfolio|^components\/portfolio\/|^lib\/actions\/portfolio|^components\/plan\/|^lib\/plan\//],
  ['divisa/formato', /^lib\/format\.ts$|^lib\/utils|^lib\/marketIndexUnit/],
  ['watchlist', /^(lib|components)\/watchlist\/|^lib\/actions\/watchlist/],
  ['alertas', /^(lib|components)\/alerts\/|^lib\/actions\/alerts/],
  ['tesis', /^lib\/thesis\/|^components\/research\/[Tt]hesis|^lib\/actions\/thesis/],
  ['Cerebro/chat', /^(lib|components)\/(chat|brain)\/|^lib\/research\/assistant|^lib\/actions\/(chat|brain)/],
  ['biblioteca/conocimiento', /^(lib|components)\/knowledge/],
  ['ficha/research', /^(lib|components)\/(research|market)\/|^lib\/actions\/research/],
  ['ajustes', /^components\/settings\/|^lib\/actions\/(settings|privacy)/],
  ['auth', /^(lib|components)\/auth\/|^lib\/better-auth|^middleware\.ts$|^lib\/security|^lib\/actions\/auth/],
];
export const OTHER = 'resto';

export function classify(file) {
  const rel = file.split(path.sep).join('/');
  for (const [name, pattern] of FEATURES) if (pattern.test(rel)) return name;
  return OTHER;
}

const pct = (covered, total) => (total === 0 ? 100 : Math.round((10000 * covered) / total) / 100);

/** summary (json-summary de Vitest) -> Map<funcionalidad, agregado>. */
export function summarize(summary, root = REPO_ROOT) {
  const out = new Map();
  for (const [file, data] of Object.entries(summary)) {
    if (file === 'total') continue;
    const rel = (path.isAbsolute(file) ? path.relative(root, file) : file).split(path.sep).join('/');
    const name = classify(rel);
    const agg = out.get(name) ?? { lines: [0, 0], branches: [0, 0], files: [] };
    agg.lines[0] += data.lines.covered;
    agg.lines[1] += data.lines.total;
    agg.branches[0] += data.branches.covered;
    agg.branches[1] += data.branches.total;
    agg.files.push({ file: rel, percent: data.lines.pct, missing: data.lines.total - data.lines.covered });
    out.set(name, agg);
  }
  for (const agg of out.values()) {
    agg.percentLines = pct(agg.lines[0], agg.lines[1]);
    agg.percentBranches = pct(agg.branches[0], agg.branches[1]);
    agg.files.sort((a, b) => b.missing - a.missing);
  }
  return out;
}

export function render(byFeature, { markdown = false, top = 3 } = {}) {
  const order = [...FEATURES.map(([n]) => n), OTHER].filter((n) => byFeature.has(n));
  const rows = [];
  if (markdown) {
    rows.push('### Cobertura frontend por funcionalidad (Vitest, informativo)', '');
    rows.push('| Funcionalidad | Líneas | Ramas | Ficheros con más hueco |', '|---|---:|---:|---|');
  }
  for (const name of order) {
    const a = byFeature.get(name);
    const worst = a.files.filter((f) => f.missing > 0).slice(0, top);
    if (markdown) {
      const w = worst.map((f) => `\`${path.basename(f.file)}\` (${f.percent}%)`).join(', ');
      rows.push(`| ${name} | ${a.percentLines}% | ${a.percentBranches}% | ${w} |`);
    } else {
      rows.push(`${name.padEnd(26)} líneas ${String(a.percentLines).padStart(6)}%  ramas ${String(a.percentBranches).padStart(6)}%`);
      for (const f of worst) rows.push(`    ${String(f.percent).padStart(6)}%  -${f.missing}l  ${f.file}`);
    }
  }
  return rows.join('\n');
}

function main(argv) {
  const markdown = argv.includes('--markdown');
  const topAt = argv.indexOf('--top');
  const top = topAt >= 0 ? Number(argv[topAt + 1]) || 3 : 3;
  const jsonAt = argv.indexOf('--json');
  if (!existsSync(SUMMARY)) {
    console.log(`(sin ${path.relative(REPO_ROOT, SUMMARY)}: ejecuta antes npm run test:coverage)`);
    return;
  }
  const byFeature = summarize(JSON.parse(readFileSync(SUMMARY, 'utf8')));
  console.log(render(byFeature, { markdown, top }));
  if (jsonAt >= 0 && argv[jsonAt + 1]) {
    writeFileSync(argv[jsonAt + 1], JSON.stringify(Object.fromEntries(byFeature), null, 2));
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2));
}
