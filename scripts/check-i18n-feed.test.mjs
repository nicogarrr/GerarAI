import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const checker = resolve('scripts/check-i18n.mjs');
function check(source, route = 'app/api/calendar-feed/[token]/route.ts') {
  const root = mkdtempSync(join(tmpdir(), 'i18n-feed-'));
  const put = (name, body) => {
    const full = join(root, name);
    mkdirSync(dirname(full), { recursive: true });
    writeFileSync(full, body);
  };
  try {
    mkdirSync(join(root, 'components'));
    put('lib/i18n/es.json', '{}');
    put(route, source);
    return spawnSync(process.execPath, [checker], { cwd: root, encoding: 'utf8' });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}
test('uniform machine ICS 404 body is allowed', () => {
  assert.equal(check("return new NextResponse('Not found', { status: 404 });").status, 0);
});
for (const source of [
  "return <p>Not found</p>;",
  "const title = 'Not found';",
  "return new NextResponse('Not found', { status: 500 });",
  "return new NextResponse('Not found', { status: 404 }); const title = 'Not found';",
]) {
  test(`feed UI and non-404 copy still fails: ${source}`, () => {
    const result = check(source);
    assert.equal(result.status, 1);
    assert.match(result.stderr, /Not found/);
  });
}
test('same response in another route is not exempt', () => {
  assert.equal(check("return new NextResponse('Not found', { status: 404 });", 'app/api/other/route.ts').status, 1);
});
