// Stryker (mutation testing) sobre las librerías de frontend de más riesgo.
// Manual, NO es un gate: `npx stryker run stryker.conf.mjs` o el workflow
// manual .github/workflows/mutation.yml. Ver docs/testing/mutation.md.
//
// Runner "command": la mayoría de los tests de estas librerías son guards
// `node --test` (scripts/*.test.ts) además de Vitest, y Stryker no tiene runner
// para node:test. El comando corre los dos grupos; cada mutante = una pasada.

const nodeTests = [
  'scripts/quote-freshness.test.ts',
  'scripts/fe-libs-golden.test.ts',
  'scripts/portfolio-cash-guard.test.ts',
  'scripts/portfolio-position-weight-guard.test.ts',
  'scripts/mutation-gaps-fe.test.ts',
];
const vitestTests = [
  'tests/unit/lib/watchlist/sort-rows.test.ts',
  'tests/unit/components/DcaLevelBadge.stale.test.tsx',
  'tests/unit/components/DcaRunStatus.test.tsx',
];

/** @type {import('@stryker-mutator/api/core').PartialStrykerOptions} */
const config = {
  mutate: [
    'lib/dca/format.ts',
    'lib/portfolio-allocation.ts',
    'lib/watchlist/sort-rows.ts',
    'lib/market/quote-freshness.ts',
  ],
  testRunner: 'command',
  commandRunner: {
    command:
      `node --experimental-strip-types --experimental-test-module-mocks --test ${nodeTests.join(' ')}` +
      ` && npx vitest run ${vitestTests.join(' ')}`,
  },
  coverageAnalysis: 'off',
  concurrency: 4,
  timeoutMS: 60000,
  reporters: ['clear-text', 'progress', 'html', 'json'],
  htmlReporter: { fileName: 'reports/mutation/mutation.html' },
  jsonReporter: { fileName: 'reports/mutation/mutation.json' },
  tempDirName: '.stryker-tmp',
  cleanTempDir: true,
};

export default config;
