// Guard: las joyas no muestran el nombre SEC en mayúsculas («COCA-COLA
// CONSOLIDATED INC»); se usa formatCompanyName como en el resto de la app.
import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const SRC = readFileSync('components/proPicks/GemsView.tsx', 'utf8');

test('GemsView formatea el nombre de empresa', () => {
  assert.match(SRC, /const \{[^}]*formatCompanyName[^}]*\} = useFormat\(\)/);
  assert.match(SRC, /formatCompanyName\(gem\.name\)/);
});
