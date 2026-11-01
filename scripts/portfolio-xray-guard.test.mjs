// Guard: the portfolio X-ray rules (idea from Ghostfolio's X-ray report) reach the
// intelligence page, and every rule/status the backend can send has es and en text.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const RULES = ['PosicionUnica', 'DivisaUnica', 'SectorUnico', 'PaisUnico'];
const page = readFileSync('app/(root)/portfolio/intelligence/page.tsx', 'utf8');

function intelligence(locale) {
  const messages = JSON.parse(readFileSync(`lib/i18n/messages/${locale}/portfolio.json`, 'utf8'));
  return messages.portfolio?.intelligence ?? messages.intelligence;
}

test('intelligence page renders the backend xray rules', () => {
  assert.match(page, /data\.xray/);
  assert.match(page, /portfolio\.intelligence\.xrayTitle/);
  for (const rule of RULES) assert.match(page, new RegExp(`portfolio\\.intelligence\\.xray${rule}Aviso`));
});

for (const locale of ['es', 'en']) {
  test(`xray texts exist in ${locale}`, () => {
    const t = intelligence(locale);
    assert.ok(t, 'intelligence block');
    assert.equal(typeof t.xrayTitle, 'string');
    assert.equal(typeof t.xraySinDatos, 'string');
    for (const rule of RULES) {
      assert.match(t[`xray${rule}Aviso`] ?? '', /\{value\}/, `xray${rule}Aviso`);
      assert.equal(typeof t[`xray${rule}Ok`], 'string', `xray${rule}Ok`);
    }
  });
}
