import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '..', 'components/common/ExtendedHoursLine.tsx'), 'utf8');

test('la linea pre/post no pinta un precio cuya divisa difiere de la del listado (ADR vs EUR)', () => {
    assert.match(source, /quote\.currency\.toUpperCase\(\) !== currency\.toUpperCase\(\)\) return null/);
});
