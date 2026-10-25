import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const checker = resolve('scripts/check-routes.mjs');
function check(href) {
  const root = mkdtempSync(join(tmpdir(), 'routes-query-'));
  const put = (name, content = '') => {
    const full = join(root, name);
    mkdirSync(full.slice(0, full.lastIndexOf('/')), { recursive: true });
    writeFileSync(full, content);
  };
  try {
    put('lib/constants.ts', 'export const NAV_ITEMS = [];');
    put('app/metodologia/page.tsx');
    put('app/api/thesis/[ticker]/pdf/route.ts');
    put('components/Links.tsx', `const links = <><a href="/metodologia"/><a href={\`${href}\`}/></>;`);
    return spawnSync(process.execPath, [checker], { cwd: root, encoding: 'utf8' });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

for (const href of [
  '/api/thesis/${encoded}/pdf',
  '/api/thesis/${encoded}/pdf?draft=1',
  '/api/thesis/${encoded}/pdf#download',
  '/api/thesis/${encoded}/pdf?draft=1#download',
]) {
  test(`existing PDF proxy resolves: ${href}`, () => {
    const result = check(href);
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /1 \/api hrefs resolve/);
  });
}
for (const href of ['/api/thesis/${encoded}/missing?draft=1', '/api/missing?draft=1#download']) {
  test(`missing proxy still fails: ${href}`, () => {
    const result = check(href);
    assert.equal(result.status, 1);
    assert.match(result.stderr, /no app\/api proxy/);
  });
}
