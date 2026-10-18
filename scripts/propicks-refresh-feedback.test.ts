import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
test('refresh announces consultation result without claiming a new run', () => {
  const source = readFileSync('components/proPicks/EnhancedProPicksContent.tsx', 'utf8');
  assert.match(source, /Selección consultada:/);
  assert.match(source, /0 empresas con estos filtros/);
  assert.match(source, /loading \? 'Consultando selección\.\.\.' : refreshStatus/);
  assert.match(source, /Los resultados anteriores se conservan/);
});
