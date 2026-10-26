import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const compose = readFileSync('docker-compose.prod.yml', 'utf8');
const start = compose.indexOf('\n  worker:');
const worker = compose.slice(start, compose.indexOf('\n  worker-thesis:', start));

test('el worker default de prod monta el snapshot del factsheet S&P 500 en solo lectura (#726)', () => {
  assert.match(worker, /SP500_FACTSHEET_SNAPSHOT_DIR: \$\{SP500_FACTSHEET_SNAPSHOT_DIR:-\/data\/sp500-factsheet-snapshots\}/);
  assert.match(worker, /\.\/data-sp500-factsheet-snapshots:\/data\/sp500-factsheet-snapshots:ro/);
});

test('el directorio de snapshots no se versiona ni entra en la imagen', () => {
  assert.match(readFileSync('.gitignore', 'utf8'), /^\/data-sp500-factsheet-snapshots\/$/m);
  assert.match(readFileSync('.dockerignore', 'utf8'), /^data-sp500-factsheet-snapshots\/$/m);
});
