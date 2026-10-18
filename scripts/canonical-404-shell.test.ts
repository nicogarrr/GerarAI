import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
test('lowercase ticker redirects before data loads and retains query',()=>{
 const s=readFileSync('app/(root)/research/[ticker]/page.tsx','utf8');
 const start=s.indexOf('export default async function ResearchCompanyPage');
 const page=s.slice(start);
 assert.ok(page.includes('if (rawTicker !== ticker)'));
 assert.ok(page.includes('Object.entries(query)'));
 assert.ok(page.indexOf('if (rawTicker !== ticker)')<page.indexOf('const activeView'));
});
test('404 has authenticated full shell and public fallback without redirect',()=>{
 const s=readFileSync('app/not-found.tsx','utf8');
 assert.ok(s.includes('if (authenticated) return <AuthenticatedLayout>'));
 assert.ok(s.includes('requireAuthenticatedUser()'));
 assert.ok(s.includes('Public 404 stays public'));
});
