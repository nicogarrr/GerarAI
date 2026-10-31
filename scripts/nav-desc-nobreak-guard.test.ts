import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

type Nav = { descriptions: Record<string, string> };
const load = (locale: string): Nav =>
  JSON.parse(readFileSync(new URL(`../lib/i18n/messages/${locale}/nav.json`, import.meta.url), 'utf8'));

for (const locale of ['es', 'en'] as const) {
  test(`nav ${locale}: las descripciones de /discover no parten las referencias a formularios SEC`, () => {
    const d = load(locale).descriptions;
    // NBSP entre "Form" y el numero, guion no rompible en "8-K": evita huerfanas a 390px.
    assert.match(d.insider, /Form\u00A04\./);
    assert.doesNotMatch(d.insider, /Form 4\./);
    assert.match(d.ownership, /Form\u00A013F\./);
    assert.doesNotMatch(d.ownership, /Form 13F\./);
    assert.match(d.calendarioMacro, /8\u2011K/);
    assert.doesNotMatch(d.calendarioMacro, /8-K/);
  });
}
