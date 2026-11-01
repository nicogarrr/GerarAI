import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { execFileSync } from 'node:child_process';
const source = readFileSync('.github/workflows/a11y-perf.yml', 'utf8');
test('manual ref enters shell only through quoted environment, never expression substitution', () => {
  const blocks = [...source.matchAll(/- name: Slug del ref para artefactos([\s\S]*?)(?=\n      - )/g)];
  assert.equal(blocks.length, 2);
  for (const [, block] of blocks) {
    assert.match(block, /MEASURE_REF: \$\{\{ inputs.ref \}\}/);
    const shell = block.split('run: |')[1];
    assert.doesNotMatch(shell, /\$\{\{/);
    assert.match(shell, /"\$MEASURE_REF"/);
  }
});
test('shell-like ref is sanitized as data and cannot execute or create extra environment lines', () => {
  const shell = `REF_SLUG=$(printf '%s' "$MEASURE_REF" | tr -cs 'A-Za-z0-9._-' '-'); printf '%s' "$REF_SLUG"`;
  const result = execFileSync('bash', ['-c', shell], { env: { ...process.env, MEASURE_REF: '$(echo INJECTED >&2)\nOTHER=value/x' }, encoding: 'utf8' });
  assert.equal(result, '-echo-INJECTED-2-OTHER-value-x');
});
