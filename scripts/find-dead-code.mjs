/**
 * E6: dead-code detector with reachability from real entry points.
 *
 * The naive version of this tool is "count inbound imports, report 0". That
 * version is wrong in this repo in two ways that matter:
 *
 *   1. A file imported only by another dead file is ALSO dead. `a.py` -> `b.py`
 *      where nobody imports `a.py` means `b.py` is unreachable even though it
 *      has an importer. Counting edges reports `b.py` as alive; a closure over
 *      importers never reaches it. So this computes the set REACHABLE from
 *      entry points and reports the complement.
 *
 *   2. This repo reaches a lot of code dynamically. FastAPI mounts routers with
 *      `include_router`, Dramatiq registers actors with `add_actor`, and CI
 *      invokes Playwright specs and eval runners BY PATH rather than by import,
 *      so they have zero importers while being very much alive. Every one of
 *      those is an explicit seed (see ENTRY_POINTS) or a registration call the
 *      extractor understands (see REGISTRATION_CALLS).
 *
 * Test files are never reported: pytest imports them by path, so "nobody imports
 * this test" is the normal state of a healthy test file, not evidence of death.
 *
 * Fail-closed: the whitelist is verified against the filesystem and a set of
 * files known to be alive is asserted reachable. If this scanner ever drifts
 * into false positives it exits non-zero rather than lying quietly.
 *
 * Usage:
 *   node scripts/find-dead-code.mjs            # human table
 *   node scripts/find-dead-code.mjs --json     # machine readable
 *   node scripts/find-dead-code.mjs --fail     # non-zero exit if anything is dead
 *   node scripts/find-dead-code.mjs --fail --baseline scripts/baselines/dead-code.txt
 *       # non-zero exit only on dead code NOT in the baseline; a baseline entry
 *       # that stops being a finding is fail-closed (shrink the baseline in that PR)
 */
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = resolve(fileURLToPath(new URL('..', import.meta.url)));

const CODE_EXT = ['.py', '.ts', '.tsx', '.mjs', '.js'];
const SCAN_EXT = new Set(CODE_EXT);

/** Directories never descended into for the graph (vendored/generated/binary). */
const EXCLUDED_DIRS = new Set([
  '.venv',
  'venv',
  'node_modules',
  '.next',
  '.next-e2e',
  'coverage',
  'htmlcov',
  'playwright-report',
  'test-results',
  '__pycache__',
  '.pytest_cache',
  '.ruff_cache',
  '.mypy_cache',
  'storage',
]);

/**
 * Folders whose files are ALL entry points by construction. Listed explicitly
 * rather than as a broad pattern so that an over-broad entry point is a visible,
 * reviewable list instead of a silent hole in the analysis.
 */
const ENTRY_POINTS = {
  /** Explicit single files. */
  files: [
    'data-engine/main.py',
    'data-engine/app/workers/dramatiq_app.py',
    'data-engine/alembic/env.py',
    'data-engine/quantstats/__init__.py',
    'playwright.config.ts',
    'next.config.ts',
    'postcss.config.mjs',
    'eslint.config.mjs',
    'scripts/check-bundle-budget.mjs',
    'scripts/check-i18n.mjs',
    'scripts/check-routes.mjs',
    'scripts/diagnose-db.mjs',
    'scripts/repair-auth-store.mjs',
    'scripts/test-auth-signup.mjs',
    'scripts/test-db.mjs',
    'scripts/research-assistant-guard.test.mjs',
    'scripts/research-client-contract.loader.mjs',
    'scripts/research-identity-guard.loader.mjs',
    'scripts/transaction-validation.loader.mjs',
    'infra/postgres/init.sql',
  ],
  /** Globs: every match is an entry point. */
  globs: [
    // alembic applies every migration in versions/ by filename order, it never
    // imports them.
    'data-engine/alembic/versions/*.py',
    // Evals and their runners are invoked by path from CI and from
    // scripts/run_financial_evals.py.
    'data-engine/evals/**/*.py',
    'data-engine/evals/*.py',
    // Operator scripts: `python data-engine/scripts/<name>.py`.
    'data-engine/scripts/*.py',
    // pytest imports test modules by path. A test file with no importers is
    // healthy, so tests are seeds and never reported as dead.
    'data-engine/tests/**/*.py',
    'data-engine/tests/*.py',
    // Playwright collects specs by path (playwright.config.ts testDir).
    'e2e/**/*.ts',
    'e2e/*.ts',
    // `npm run` targets and standalone node utilities.
    'scripts/*.mjs',
    'scripts/*.ts',
    'scripts/*.py',
    // Next.js file-system routing: every page/layout/route is an entry.
    'app/**/page.tsx',
    'app/**/layout.tsx',
    'app/**/route.ts',
    'app/**/template.tsx',
    'app/**/loading.tsx',
    'app/**/error.tsx',
    'app/**/not-found.tsx',
    'app/**/global-error.tsx',
    'app/**/default.tsx',
    'app/**/sitemap.ts',
    'app/**/robots.ts',
    // Next.js metadata file convention: discovered by the framework, not imported.
    'app/**/manifest.ts',
    // Ambient type declarations: pulled in by tsconfig `include: **\/*.ts`, not
    // imported. `types/global.d.ts` declares globals for the whole app.
    'types/**/*.d.ts',
    // Infrastructure and DB migrations are applied by external tooling.
    'database/**/*.sql',
    'infra/**/*.sql',
  ],
  /**
   * Next.js only routes `page`/`layout`/... but a component in `components/` is
   * reachable only through imports, which the graph already follows.
   */
  neverReport: [
    'data-engine/tests/**',
    'data-engine/evals/**',
    'data-engine/scripts/**',
    'data-engine/alembic/versions/**',
    'e2e/**',
    'data-engine/quantstats/**',
    // Next serves `public/` by URL, never by import. `public/sw.js` in
    // particular is registered from a raw string in app/layout.tsx:67
    // (`navigator.serviceWorker.register('/sw.js')`), so no import graph can
    // ever show it as live.
    'public/**',
    // `__init__.py` is a package marker, not code. Deleting one is churn that
    // can only break import resolution, never remove behaviour.
    '**/__init__.py',
  ],
};

/**
 * Files asserted ALIVE. If the scanner reports any of these as dead it is
 * wrong, and it exits non-zero instead of publishing a bogus finding.
 * Each one is here because a plausible reader would expect a naive scanner to
 * flag it: they are reached dynamically, or only from tests, or are vendored.
 */
const KNOWN_ALIVE = [
  // Imported by tests/test_portfolio_risk_metrics.py as quantstats.montecarlo.
  'data-engine/quantstats/montecarlo/analytics.py',
  // FastAPI mounts every route module through app/api/router.py.
  'data-engine/app/api/routes/companies.py',
  'data-engine/app/api/routes/propicks.py',
  // Evals gate: reached by path from CI, not by import.
  'data-engine/evals/gates.py',
];

/**
 * Calls whose string arguments name modules that must be treated as imports.
 * These are the dynamic-registration edges: if FastAPI ever receives a router by
 * module path, or a worker loads an actor by name, the module is alive even
 * though nothing imports it literally.
 */
const REGISTRATION_CALLS = [
  'include_router',
  'add_api_route',
  'add_actor',
  'add_middleware',
  'import_module',
  '__import__',
  'worker_class',
  'mount',
  'walk_packages',
  'iter_modules',
];

// ---------------------------------------------------------------- git + io

function trackedFiles() {
  const out = execFileSync('git', ['ls-files', '-z'], {
    cwd: REPO,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  return out.split('\0').filter(Boolean);
}

function isScannable(rel) {
  if (!SCAN_EXT.has(extname(rel))) return false;
  const parts = rel.split('/');
  return !parts.some((p) => EXCLUDED_DIRS.has(p));
}

function extname(p) {
  const i = p.lastIndexOf('.');
  return i === -1 ? '' : p.slice(i);
}

function toPosix(p) {
  return p.split('\\').join('/');
}

/** Normalize a joined path to a repo-relative POSIX path (or '' if it escapes). */
function resolveRepo(p) {
  const abs = resolve(REPO, toPosix(p));
  if (abs !== REPO && !abs.startsWith(REPO + '/') && !abs.startsWith(REPO + '\\')) return '';
  return toPosix(abs.slice(REPO.length).replace(/^[/\\]+/, ''));
}

/** Minimal glob: supports `**` and `*`, no character classes. */
function globToRe(glob) {
  let re = '';
  for (let i = 0; i < glob.length; i++) {
    const c = glob[i];
    if (c === '*') {
      if (glob[i + 1] === '*') {
        // `**/` matches zero or more directories.
        if (glob[i + 2] === '/') {
          re += '(?:.*/)?';
          i += 2;
        } else {
          re += '.*';
          i += 1;
        }
      } else {
        re += '[^/]*';
      }
    } else if ('.^$+{}()|[]\\?'.includes(c)) {
      re += `\\${c}`;
    } else {
      re += c;
    }
  }
  return new RegExp(`^${re}$`);
}

// ------------------------------------------------------- import extraction

const PY_IMPORT_RE = /^[ \t]*(?:from[ \t]+([.\w]+)[ \t]+import\b|import[ \t]+([^\n#]+))/gm;
// The name list may be parenthesised: after normalizePyImports it is on one line
// as `(alerts, asts, ...)`, so the capture must accept the leading `(`.
const PY_FROM_BARE_RE = /^[ \t]*from[ \t]+([.\w]+)[ \t]+import[ \t]+([^\n]+)/gm;

const TS_IMPORT_RE =
  /(?:^|[\s(=;,])(?:import|export)(?:\s+type)?(?:\s+[\w*{}\n\r\t, $]+\s+from)?\s*['"]([^'"]+)['"]/g;
const DYNAMIC_IMPORT_RE = /\b(?:import|require)\s*\(\s*['"]([^'"]+)['"]\s*\)/g;
const STRINGY_IMPORT_RE = /\b(?:import_module|__import__)\s*\(\s*['"]([^'"]+)['"]/g;
const REGISTRATION_RE = new RegExp(
  `\\b(?:${REGISTRATION_CALLS.join('|')})\\s*\\(([^)]{0,400})`,
  'g',
);
const QUOTED_RE = /['"]([^'"]+)['"]/g;

/** Strip comments and string noise that would otherwise look like imports. */
function stripNoise(src, lang) {
  let s = src;
  if (lang === 'py') {
    s = s.replace(/"""[\s\S]*?"""/g, '""').replace(/'''[\s\S]*?'''/g, "''");
    s = s.replace(/#[^\n]*/g, '');
  } else {
    // Preserve import specifiers; only drop comments and template literals.
    s = s.replace(/\/\*[\s\S]*?\*\//g, '');
    s = s.replace(/(^|[^:])\/\/[^\n]*/g, '$1');
  }
  return s;
}

/**
 * `from app.api.routes import (\n  alerts,\n  asts,\n)` is how
 * app/api/router.py mounts every FastAPI router. A line-oriented regex sees
 * `import (` and stops, so all ~38 route modules look like they have zero
 * importers. Collapse the parenthesised name list onto one line first.
 */
function normalizePyImports(src) {
  let prev;
  let out = src;
  do {
    prev = out;
    out = out.replace(
      /(from\s+[.\w]+\s+import\s*)\(([^)]*)\)/g,
      (_m, head, names) => `${head}(${names.replace(/\s+/g, ' ').trim()})`,
    );
  } while (out !== prev);
  return out;
}

/**
 * Pull every import-ish specifier out of a source file.
 * Returns raw specifiers (relative paths and dotted module names) plus the
 * registration-call string arguments, which the caller resolves the same way.
 */
function extractSpecs(rel, src) {
  const lang = extname(rel) === '.py' ? 'py' : 'ts';
  const body = stripNoise(lang === 'py' ? normalizePyImports(src) : src, lang);
  const specs = new Set();

  if (lang === 'py') {
    for (const m of body.matchAll(PY_FROM_BARE_RE)) {
      specs.add(m[1]);
      for (const part of m[2].split(',')) {
        const name = part
          .trim()
          .replace(/^\(+/, '')
          .replace(/\)+$/, '')
          .split(/\s+as\s+/)[0]
          .trim();
        if (name && name !== '*') specs.add(`${m[1]}.${name}`);
      }
    }
    for (const m of body.matchAll(PY_IMPORT_RE)) {
      const mod = m[1] ?? m[2];
      if (!mod) continue;
      for (const part of mod.split(',')) {
        const name = part.trim().split(/\s+as\s+/)[0].trim();
        if (name && name !== '*') specs.add(name);
      }
    }
  } else {
    for (const m of body.matchAll(TS_IMPORT_RE)) specs.add(m[1]);
    for (const m of body.matchAll(DYNAMIC_IMPORT_RE)) specs.add(m[1]);
  }

  // `import_module("app.services.x")` / `__import__("y")` in either language.
  for (const m of body.matchAll(STRINGY_IMPORT_RE)) specs.add(m[1]);

  // Registration calls: string arguments name modules reached dynamically.
  // `include_router("app.api.routes.x.router")` and `add_actor("app.workers.y.act")`
  // are the shapes that would fool a literal-import scanner.
  for (const m of body.matchAll(REGISTRATION_RE)) {
    for (const q of m[1].matchAll(QUOTED_RE)) {
      const arg = q[1];
      if (/^[.\w/-]+$/.test(arg)) specs.add(arg);
    }
  }
  return [...specs];
}

// -------------------------------------------------------------- resolution

/** Python source roots: `data-engine/` is the import root (pythonpath = ["."]). */
const PY_ROOTS = ['data-engine'];
/** TS path alias from tsconfig.json paths. */
const TS_ALIASES = [['@/', '']];

function existsFile(rel) {
  return rel.length > 0 && existsSync(join(REPO, rel));
}

function firstExisting(candidates) {
  for (const c of candidates) if (existsFile(c)) return c;
  return null;
}

/** Resolve a dotted python module name (or relative spec) to a repo path. */
function resolvePython(spec, fromRel) {
  const fromDir = fromRel.includes('/') ? fromRel.slice(0, fromRel.lastIndexOf('/')) : '';
  let mod = spec;
  let baseDir = '';

  if (mod.startsWith('.')) {
    const dots = /^\.+/.exec(mod)[0].length;
    mod = mod.slice(dots);
    const parts = fromDir.split('/').filter(Boolean);
    const up = parts.slice(0, Math.max(0, parts.length - (dots - 1)));
    baseDir = up.join('/');
  } else {
    baseDir = null; // absolute: search every python root
  }

  const segs = mod ? mod.split('.') : [];
  const roots = baseDir === null ? PY_ROOTS.map((r) => (r ? `${r}/` : '')) : [baseDir ? `${baseDir}/` : ''];

  for (const root of roots) {
    const stem = root + segs.join('/');
    const hit = firstExisting([
      `${stem}.py`,
      `${stem}/__init__.py`,
      `${stem}.pyi`,
    ]);
    if (hit) return hit;
  }
  return null;
}

const TS_EXTS = ['.ts', '.tsx', '.mjs', '.js'];

function resolveTs(spec, fromRel) {
  if (!spec) return null;
  const fromDir = fromRel.includes('/') ? fromRel.slice(0, fromRel.lastIndexOf('/')) : '';

  if (spec.startsWith('.')) {
    const stem = resolveRepo(toPosix(join(fromDir, spec)));
    const hit = firstExisting([
      ...TS_EXTS.map((e) => `${stem}${e}`),
      ...TS_EXTS.map((e) => `${stem}/index${e}`),
    ]);
    if (hit) return hit;
  }
  for (const [alias, target] of TS_ALIASES) {
    if (spec.startsWith(alias)) {
      const stem = target + spec.slice(alias.length);
      const hit = firstExisting([
        ...TS_EXTS.map((e) => `${stem}${e}`),
        ...TS_EXTS.map((e) => `${stem}/index${e}`),
      ]);
      if (hit) return hit;
    }
  }
  return null;
}

/** Accept either a TS specifier or a python dotted name; try both. */
function resolveAny(spec, fromRel) {
  if (extname(fromRel) === '.py') {
    const py = resolvePython(spec, fromRel);
    if (py) return py;
  }
  const ts = resolveTs(spec, fromRel);
  if (ts) return ts;
  // Registration strings are often dotted even in a .py caller; retry as python
  // regardless of the caller's language.
  return resolvePython(spec.replace(/\//g, '.'), fromRel);
}

// ------------------------------------------------------ CI path references

/**
 * A file that mentions another tracked file's path is a live reference, not a
 * dead one. This matters far more than it looks: the ~130 `scripts/*-guard.test.ts`
 * do not import the components they police, they `readFileSync` them by path, so
 * an import-graph-only scanner reports half the guarded UI as dead and invites
 * someone to delete the thing a guard exists to protect.
 *
 * Only EXECUTABLE referrers count. A path mentioned in `docs/` or a README is
 * prose and proves nothing, so markdown is excluded on purpose.
 */
const REFERRER_GLOBS = [
  '.github/workflows/*.yml',
  '.github/workflows/*.yaml',
  'Dockerfile',
  'Dockerfile.*',
  'data-engine/Dockerfile*',
  'package.json',
  'playwright.config.ts',
  'data-engine/alembic.ini',
  'data-engine/pyproject.toml',
  'docker-compose*.yml',
  'render.yaml',
  'scripts/*',
  'e2e/*',
  'data-engine/tests/*',
  'data-engine/scripts/*',
  'data-engine/evals/*',
];

function harvestPathReferences(allFiles) {
  const text = [];
  for (const rel of allFiles) {
    if (REFERRER_GLOBS.some((g) => globToRe(g).test(rel))) {
      try {
        text.push({ rel, body: readFileSync(join(REPO, rel), 'utf8') });
      } catch {
        /* unreadable referrer is reported by the hygiene guard, not here */
      }
    }
  }

  const fileSet = new Set(allFiles);
  const stems = new Map(); // "run_financial_evals" -> candidates
  for (const f of allFiles) {
    if (!SCAN_EXT.has(extname(f))) continue;
    const stem = f.split('/').pop().replace(/\.[^.]+$/, '');
    if (!stems.has(stem)) stems.set(stem, []);
    stems.get(stem).push(f);
  }

  const found = new Set();
  for (const { rel, body } of text) {
    // Any tracked path mentioned verbatim.
    for (const f of fileSet) {
      if (f.length < 6) continue;
      if (body.includes(f)) found.add(f);
    }
    // A bare basename (`CollapsiblePanel`, `ProPicksSection.tsx`) is how a guard
    // test usually names its target, sometimes only to assert it does NOT exist.
    for (const f of fileSet) {
      if (!SCAN_EXT.has(extname(f))) continue;
      const base = f.split('/').pop().replace(/\.[^.]+$/, '');
      if (base.length >= 8 && new RegExp(`\\b${base}\\b`).test(body)) found.add(f);
    }
    // Explicit extension-bearing names (`python scripts/run_financial_evals.py`).
    for (const m of body.matchAll(/([\w./-]+\.(?:py|mjs|ts|tsx|js|sql|sh|ps1))/g)) {
      const cand = m[1].replace(/^\.\//, '');
      if (fileSet.has(cand)) found.add(cand);
    }
    // Dotted module paths (`app.services.x`) that name a tracked module.
    for (const m of body.matchAll(/\b(app|modules|quantstats)\.[\w.]+/g)) {
      const spec = m[0];
      const py = resolvePython(spec, `${rel}`);
      if (py) found.add(py);
    }
  }
  return found;
}

// --------------------------------------------------------------- the graph

function buildGraph(allFiles) {
  const nodes = allFiles.filter(isScannable);
  const nodeSet = new Set(nodes);
  /** @type {Map<string, Set<string>>} importer -> imported */
  const edges = new Map();
  /** @type {Map<string, string[]>} imported -> importers */
  const importers = new Map();
  /** @type {Map<string, Set<string>>} file -> unresolved specifiers */
  const unresolved = new Map();

  for (const n of nodes) {
    edges.set(n, new Set());
    importers.set(n, new Set());
  }

  for (const n of nodes) {
    let src;
    try {
      src = readFileSync(join(REPO, n), 'utf8');
    } catch {
      continue;
    }
    const bad = new Set();
    for (const spec of extractSpecs(n, src)) {
      // Skip obvious third-party / stdlib names cheaply: a resolution miss on a
      // bare word is normal (numpy, fastapi), a miss on a path is interesting.
      const target = resolveAny(spec, n);
      if (target && nodeSet.has(target) && target !== n) {
        edges.get(n).add(target);
        importers.get(target).add(n);
      } else if (target === null && /[./]/.test(spec)) {
        bad.add(spec);
      }
    }
    if (bad.size) unresolved.set(n, [...bad]);
  }

  return { nodes, nodeSet, edges, importers, unresolved };
}

// ------------------------------------------------------------------- report

function human(bytes) {
  const u = ['B', 'kB', 'MB', 'GB'];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v < 10 && i > 0 ? v.toFixed(1) : Math.round(v)} ${u[i]}`;
}

function main() {
  const argv = process.argv.slice(2);
  const args = new Set(argv);
  const asJson = args.has('--json');
  const failOnDead = args.has('--fail');
  // --baseline <fichero>: lista de inertes conocidos (uno por linea, # comenta).
  // Con baseline, --fail solo rompe por muertos NUEVOS; una entrada de la
  // baseline que ya no es hallazgo (borrada o revivida) es fallo cerrado:
  // la baseline se encoge en el mismo PR que limpia, nunca se acumula.
  const baselineIdx = argv.indexOf('--baseline');
  const baselinePath = baselineIdx >= 0 ? argv[baselineIdx + 1] : null;
  let baseline = null;
  if (baselinePath) {
    if (!baselinePath || baselinePath.startsWith('--') || !existsSync(resolve(REPO, baselinePath))) {
      console.error(`--baseline: fichero no encontrado: ${baselinePath ?? '(sin valor)'}`);
      process.exit(2);
    }
    baseline = new Set(
      readFileSync(resolve(REPO, baselinePath), 'utf8')
        .split('\n')
        .map((l) => l.trim())
        .filter((l) => l && !l.startsWith('#')),
    );
  }
  const allFiles = trackedFiles();
  const { nodes, nodeSet, edges, importers } = buildGraph(allFiles);
  const files = new Map(nodes.map((n) => [n, statSync(join(REPO, n)).size]));

  // --- seeds
  const globRes = ENTRY_POINTS.globs.map((g) => globToRe(g));
  const seeds = new Set();
  const seedReason = new Map();
  const addSeed = (f, why) => {
    if (!nodeSet.has(f)) return;
    if (!seedReason.has(f)) seedReason.set(f, []);
    seedReason.get(f).push(why);
    seeds.add(f);
  };

  const staleWhitelist = [];
  for (const f of ENTRY_POINTS.files) {
    if (!existsFile(f)) staleWhitelist.push(f);
  }
  for (const f of ENTRY_POINTS.files) if (nodeSet.has(f)) addSeed(f, 'whitelist:file');

  for (const n of nodes) {
    for (let i = 0; i < globRes.length; i++) {
      if (globRes[i].test(n)) addSeed(n, `whitelist:${ENTRY_POINTS.globs[i]}`);
    }
  }
  for (const f of harvestPathReferences(allFiles)) addSeed(f, 'referenced-by-ci/config');

  // --- reachability closure over importers
  const reachable = new Set(seeds);
  const queue = [...seeds];
  while (queue.length) {
    const cur = queue.pop();
    for (const dep of edges.get(cur) ?? []) {
      if (!reachable.has(dep)) {
        reachable.add(dep);
        queue.push(dep);
      }
    }
  }

  // --- never-report filters
  const neverRes = ENTRY_POINTS.neverReport.map((g) => globToRe(g));
  const isNever = (n) => neverRes.some((r) => r.test(n));

  // --- findings
  const findings = [];
  for (const n of nodes) {
    if (reachable.has(n) || isNever(n)) continue;
    const ins = [...(importers.get(n) ?? [])];
    const liveIns = ins.filter((i) => reachable.has(i));
    findings.push({
      file: n,
      bytes: files.get(n) ?? 0,
      importers: ins,
      reachableImporters: liveIns,
      confidence: ins.length === 0 ? 'certain' : 'orphan-cluster',
      // `orphan-cluster` means: has importers, but every one of them is itself
      // unreachable. `certain` means: zero importers anywhere in the repo.
      why:
        ins.length === 0
          ? 'cero importadores en todo el repo (estatico, dinamico y registro)'
          : `importado solo por ${ins.length} fichero(s) igualmente inalcanzable(s)`,
    });
  }
  findings.sort((a, b) => b.bytes - a.bytes);

  // --- baseline de inertes conocidos
  let newFindings = findings;
  let staleBaseline = [];
  if (baseline !== null) {
    const found = new Set(findings.map((f) => f.file));
    newFindings = findings.filter((f) => !baseline.has(f.file));
    staleBaseline = [...baseline].filter((f) => !found.has(f));
  }

  // --- fail-closed self checks
  const failures = [];
  if (staleBaseline.length) {
    failures.push({
      check: 'baseline-stale',
      detail:
        'entradas de la baseline que ya no son hallazgo (borradas o revividas); ' +
        `quitalas de la baseline en este PR: ${staleBaseline.join(', ')}`,
    });
  }
  if (staleWhitelist.length) {
    failures.push({
      check: 'whitelist-stale',
      detail: `entradas de la lista blanca que ya no existen: ${staleWhitelist.join(', ')}`,
    });
  }
  const missingKnown = KNOWN_ALIVE.filter((f) => !existsFile(f));
  if (missingKnown.length) {
    failures.push({
      check: 'known-alive-missing',
      detail: `KNOWN_ALIVE referencia ficheros inexistentes: ${missingKnown.join(', ')}`,
    });
  }
  const falsePositives = findings.filter((f) => KNOWN_ALIVE.includes(f.file));
  if (falsePositives.length) {
    failures.push({
      check: 'false-positive',
      detail: `el escaner marco muerto algo que se sabe vivo: ${falsePositives
        .map((f) => f.file)
        .join(', ')}`,
    });
  }
  const reachableTests = [...reachable].filter((f) => f.startsWith('data-engine/tests/')).length;
  if (reachableTests === 0) {
    failures.push({
      check: 'tests-not-seeded',
      detail: 'ningun test es punto de entrada: la lista blanca de tests se rompio',
    });
  }

  const report = {
    scanned: nodes.length,
    reachable: [...reachable].filter((n) => nodeSet.has(n)).length,
    seeds: seeds.size,
    dead: findings.length,
    deadBytes: findings.reduce((a, f) => a + f.bytes, 0),
    reachableTests,
    findings,
    newFindings,
    baseline: baseline === null ? null : { path: baselinePath, known: baseline.size, stale: staleBaseline },
    selfCheckFailures: failures,
  };

  if (asJson) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(`E6 dead-code: ${report.scanned} ficheros analizados, ${report.seeds} puntos de entrada`);
    console.log(`  alcanzables: ${report.reachable}   muertos: ${report.dead}   tests como entrada: ${report.reachableTests}`);
    if (findings.length) {
      console.log('');
      const w = Math.max(...findings.map((f) => f.file.length));
      for (const f of findings) {
        console.log(
          `  ${f.file.padEnd(w)}  ${human(f.bytes).padStart(8)}  [${f.confidence}]  ${f.why}`,
        );
      }
      console.log(`\n  total muerto: ${human(report.deadBytes)}`);
    } else {
      console.log('  sin codigo muerto');
    }
    if (failures.length) {
      console.log('\n  AUTOCOMPROBACION FALLIDA:');
      for (const f of failures) console.log(`   - ${f.check}: ${f.detail}`);
    }
  }

  if (failures.length) process.exit(2);
  if (baseline !== null && newFindings.length) {
    console.log(`\n  muertos NUEVOS (no en baseline ${baselinePath}):`);
    for (const f of newFindings) console.log(`   - ${f.file}`);
  }
  if (failOnDead && newFindings.length) process.exit(1);
}

main();