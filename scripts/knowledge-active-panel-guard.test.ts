import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');

test('library only constructs the selected panel on the server', () => {
  for (const key of ['biblioteca', 'subir', 'principios']) {
    const condition = `{activeTab === TABS.${key} ? (`;
    assert.ok(source.includes(condition), `${key} has a server selection boundary`);
    const start = source.indexOf(condition);
    const panel = source.indexOf('<TabsContent', start);
    const close = source.indexOf('</TabsContent>', panel);
    assert.ok(source.slice(panel, close).includes(`value={TABS.${key}}`));
    assert.match(source.slice(close + '</TabsContent>'.length), /^\s*\) : null}/);
  }
});

test('library keeps all URL tabs and the active panel value', () => {
  assert.ok(source.includes('value={activeTab}'));
  assert.ok(source.includes("['biblioteca', 'principios', 'subir'] as TabKey[]")); 
  assert.ok(source.includes('documentReaderHref(document.id, documentOffset, searchQuery)'));
  assert.ok(source.includes('value={TABS.subir}'));
  assert.ok(source.includes('value={TABS.principios}'));
});
