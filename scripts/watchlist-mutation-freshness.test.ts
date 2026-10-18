import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
test('membership reads bypass per-instance TTL and mutations revalidate both views', () => {
 const source = readFileSync('lib/actions/watchlist.actions.ts', 'utf8');
 assert.ok(!source.includes('cachedFetch('));
 assert.equal((source.match(/revalidatePath\('\/watchlist'\)/g) ?? []).length, 2);
 assert.equal((source.match(/revalidatePath\(`\/research\//g) ?? []).length, 2);
});
