import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { afterEach, test } from 'node:test';
register('./quote-recovery.loader.mjs', import.meta.url);
// @ts-expect-error explicit extension for node strip types.
const { GET } = await import('../app/api/companies/[ticker]/extended-quote/route.ts');
const original = globalThis.fetch;
afterEach(() => { globalThis.fetch = original; });
const invoke = (ticker: string, recover = true) => GET(new Request(`http://localhost/api/companies/${ticker}/extended-quote${recover ? '?resolveListing=1' : ''}`), {params:Promise.resolve({ticker})});
function serve(company: unknown, expectedSymbol?: string) {
  const paths: string[] = [];
  globalThis.fetch = (async (url: RequestInfo | URL) => {
    const path = new URL(String(url)).pathname;
    paths.push(path);
    if (paths.length === 1) return Response.json(company);
    assert.equal(path, `/api/companies/${expectedSymbol}/extended-quote`);
    return Response.json({status:'available', ticker:expectedSymbol, price:123});
  }) as typeof fetch;
  return paths;
}
test('missing SSR identity recovers US from backend master, never guesses', async () => {
  const paths=serve({ticker:'AAPL',exchange:'NASDAQ NMS - GLOBAL MARKET',currency:'USD'}, 'AAPL');
  const r=await invoke('AAPL'); assert.equal(r.status,200);
  assert.equal((await r.json()).price,123); assert.equal(paths.length,2);
});
test('recovery respects canonical master listing, not naked Spanish US namesake', async () => {
  const paths=serve({ticker:'ALM',exchange:'BME',currency:'EUR'}, 'ALM.MC');
  const r=await invoke('ALM'); assert.equal(r.status,200);
  assert.equal((await r.json()).ticker,'ALM.MC'); assert.equal(paths.length,2);
});
test('unknown listing and missing company never reach quote provider', async () => {
  for (const company of [{ticker:'ALM',exchange:'UNKNOWN',currency:'EUR'}, {}]) {
    const paths=serve(company);const r=await invoke('ALM');assert.equal(r.status,200);assert.deepEqual(await r.json(),{status:'unavailable'});assert.equal(r.headers.get('Cache-Control'),'no-store');assert.equal(paths.length,1);
  }
});
test('master error is unavailable, not a fallback to US', async () => {
  let calls=0;globalThis.fetch=(async()=>{calls++;return Response.json({detail:'down'},{status:503});}) as typeof fetch;
  const r=await invoke('ALM');assert.equal(r.status,502);assert.equal(calls,1);
});
test('known listing retains direct one-request path', async () => {
  const paths:string[]=[];globalThis.fetch=(async(url:RequestInfo|URL)=>{paths.push(String(url));return Response.json({status:'available'});}) as typeof fetch;
  assert.equal((await invoke('AENA.MC',false)).status,200);assert.equal(paths.length,1);assert.match(paths[0]??'',/AENA.MC\/extended-quote$/);
});

test('effective specific function budget exceeds the shared 18s recovery deadline', () => {
  const config = JSON.parse(readFileSync('vercel.json','utf8'));
  const functions = Object.keys(config.functions);
  const specific = 'app/api/companies/**/extended-quote/route.ts';
  assert.ok(functions.indexOf(specific) < functions.indexOf('app/**/route.ts'));
  assert.equal(config.functions[specific].maxDuration,30);
  assert.ok(config.functions[specific].maxDuration * 1000 > 18000 + 6000);
  const route=readFileSync('app/api/companies/[ticker]/extended-quote/route.ts','utf8');
  assert.match(route,/AbortSignal.timeout\(18000\)/);
});
