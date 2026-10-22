import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync('lib/actions/market.actions.ts', 'utf8');
function loadAction(reply) {
  const loadedModule = { exports: {} };
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  vm.runInNewContext(code, {
    exports: loadedModule.exports, module: loadedModule,
    require(path) {
      if (path.includes('research/client')) return { researchRequest: reply };
      if (path.includes('memoryTTL')) return { cachedFetch: (_key, fetcher) => fetcher() };
      if (path.includes('marketIndexUnit')) return { marketIndexUnit: () => undefined };
      throw new Error(`Unexpected import ${path}`);
    },
  });
  return loadedModule.exports;
}
const empty = { as_of: null, universe: 0, gainers: [], losers: [], most_active: [] };

test('universo realmente vacío es un resultado correcto, no una caída', async () => {
  const action = loadAction(async () => empty);
  const result = await action.getMarketMoversResult(25);
  assert.equal(result.data, empty);
  assert.equal(result.error, null);
});

for (const statusCode of [401, 403, 503]) {
  test(`preserva el error ${statusCode}, sin convertirlo en datos vacíos`, async () => {
    const error = Object.assign(new Error('test-only backend detail'), { statusCode });
    const action = loadAction(async () => { throw error; });
    const result = await action.getMarketMoversResult();
    assert.equal(result.data, null);
    assert.equal(result.error, error);
    // El contrato legacy no cambia para consumidores de solo datos.
    assert.equal((await action.getMarketMovers()).universe, 0);
  });
}
test('payload inválido no finge un universo sin movimientos', async () => {
  const action = loadAction(async () => ({ universe: 0, gainers: [] }));
  const result = await action.getMarketMoversResult();
  assert.equal(result.data, null);
  assert.ok(result.error);
});
test('Mercado consume resultado discriminado y solo 5xx/red degradan a offline', () => {
  const page = readFileSync('app/(root)/screener/page.tsx', 'utf8');
  assert.match(page, /getMarketMoversResult\(25\)/);
  assert.match(page, /if \(!moversResult.data\) throw moversResult.error/);
  assert.match(page, /if \(isBackendUnavailableError\(error\)\)\s*\{\s*return <BackendOffline/);
  assert.match(page, /throw error;/);
  assert.doesNotMatch(page, /\{moversResult\.error\}/);
});
