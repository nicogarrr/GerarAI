/**
 * Runner del bundle de guards.
 *
 * Descubre `scripts/*.test.{ts,mjs}` por glob y los ejecuta todos en una sola
 * invocacion de `node --test`. El bundle se define por convencion de nombre,
 * no por una lista manual en package.json: asi un guard nuevo se ejecuta sin
 * que nadie se acuerde de cablearlo (5 guards existian, pasaban y no
 * corrian nunca en ningun sitio).
 *
 * Contrato:
 *  - descubrimiento por `node:fs` + `path` (nunca separadores hardcodeados),
 *    para que funcione igual en Windows (dev) y Linux (CI);
 *  - `cwd` = raiz del repo, porque los guards leen el codigo con rutas
 *    relativas al repo (`readFileSync('components/...')`);
 *  - salida heredada de `node:test` sin filtrar;
 *  - exit code propagado tal cual: un guard rojo hunde el script.
 */
import { spawnSync } from 'node:child_process';
import { mkdirSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SCRIPTS_DIR = path.join(REPO_ROOT, 'scripts');

let entries = [];
try {
  entries = readdirSync(SCRIPTS_DIR, { withFileTypes: true });
} catch (error) {
  console.error(`run-guards: no se pudo leer ${SCRIPTS_DIR}: ${error.message}`);
  process.exit(1);
}

const guards = entries
  .filter((entry) => entry.isFile() && /\.test\.(ts|mjs)$/.test(entry.name))
  .map((entry) => entry.name)
  .sort();

if (guards.length === 0) {
  // Fallo cerrado: un bundle vacio por un glob roto pasaria en verde y no
  // comprobaria nada. Un guard que no corre es un guard que no existe.
  console.error('run-guards: no se encontro ningun scripts/*.test.{ts,mjs} (bundle vacio).');
  process.exit(1);
}

const files = guards.map((name) => path.posix.join('scripts', name));

console.log(`run-guards: ${files.length} guard(s) descubiertos en scripts/*.test.{ts,mjs}`);

// `--coverage`: además mide qué líneas de lib/, components/ y middleware.ts
// ejecutan los guards (cobertura nativa de node:test) y la deja en LCOV para
// scripts/frontend-coverage-summary.mjs. Sin el flag, el runner es el de
// siempre. Ver docs/FRONTEND_TESTS.md.
const withCoverage = process.argv.includes('--coverage');
const coverageArgs = withCoverage
  ? [
      '--experimental-test-coverage',
      '--test-coverage-include=lib/**',
      '--test-coverage-include=components/**',
      '--test-coverage-include=middleware.ts',
      '--test-reporter=spec',
      '--test-reporter-destination=stdout',
      '--test-reporter=lcov',
      `--test-reporter-destination=${path.posix.join('coverage', 'frontend', 'guards.lcov')}`,
    ]
  : [];
if (withCoverage) mkdirSync(path.join(REPO_ROOT, 'coverage', 'frontend'), { recursive: true });

const result = spawnSync(process.execPath, ['--experimental-strip-types', '--experimental-test-module-mocks', ...coverageArgs, '--test', ...files], {
  cwd: REPO_ROOT,
  stdio: 'inherit',
});

if (result.error) {
  console.error(`run-guards: no se pudo lanzar node --test: ${result.error.message}`);
  process.exit(1);
}

if (result.signal) {
  console.error(`run-guards: node --test terminado por la senal ${result.signal}.`);
  process.exit(1);
}

process.exitCode = result.status === null ? 1 : result.status;
