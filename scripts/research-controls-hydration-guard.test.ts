import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
for (const [path, disabled] of [
 ['components/ui/panel.tsx', /disabled=\{!hydrated\}/],
 ['components/research/QuickAlertButton.tsx', /disabled=\{busy \|\| !hydrated\}/],
] as const) test(`${path}: server control cannot accept a click before hydration`, () => {
 // El botón de alerta rápida separó el cuerpo del popover en un chunk
 // diferido (QuickAlertPopoverBody): el control con el disabled vive allí.
 const src = path.includes('QuickAlertButton')
  ? readFileSync(path, 'utf8') + readFileSync('components/research/QuickAlertPopoverBody.tsx', 'utf8')
  : readFileSync(path, 'utf8');
 assert.match(src, /useSyncExternalStore/);
 assert.match(src, disabled);
});
