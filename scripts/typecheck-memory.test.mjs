import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const read = (file) => JSON.parse(readFileSync(file, 'utf8'));

test('complete typecheck gets a bounded heap, rather than the small automatic V8 heap', () => {
  const command = read('package.json').scripts.typecheck;
  assert.equal(command, 'node --max-old-space-size=1408 node_modules/typescript/bin/tsc --noEmit');
  const limit = spawnSync(process.execPath, ['--max-old-space-size=1408', '-e', 'console.log(require("node:v8").getHeapStatistics().heap_size_limit)'], { encoding: 'utf8' });
  assert.equal(limit.status, 0, limit.stderr);
  const bytes = Number(limit.stdout.trim());
  assert.ok(bytes > 1408 * 1024 * 1024 && bytes < 1536 * 1024 * 1024, String(bytes));
});

test('the original complete root universe and strict diagnostics stay enabled', () => {
  const config = read('tsconfig.json');
  assert.equal(config.compilerOptions.strict, true);
  assert.equal(config.compilerOptions.noEmit, true);
  assert.equal(config.compilerOptions.incremental, true);
  assert.notEqual(config.compilerOptions.noCheck, true);
  assert.ok(config.include.includes('**/*.ts'));
  assert.ok(config.include.includes('**/*.tsx'));
  assert.deepEqual(config.exclude, ['node_modules', 'qa-e2e']);
});

test('hook and CI use the same full typecheck command', () => {
  assert.match(readFileSync('.githooks/pre-push', 'utf8'), /npm run typecheck \|\| rc=1/);
  assert.match(readFileSync('.github/workflows/ci.yml', 'utf8'), /run: npm run typecheck/);
});
