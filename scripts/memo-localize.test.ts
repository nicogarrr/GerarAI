import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: extensión explícita para node --experimental-strip-types.
import { cleanThesisMarkdown } from '../lib/research/thesis-text.ts';

describe('memo: números y fechas es-ES', () => {
    it('porcentaje con punto pasa a coma', () => {
        assert.equal(cleanThesisMarkdown('Margen 36.2% y -4.5 %'), 'Margen 36,2\u00A0% y -4,5\u00A0%');
    });
    it('no toca versiones ni URLs', () => {
        assert.equal(cleanThesisMarkdown('v1.2.3% https://x.com/a?p=1.5%'), 'v1.2.3% https://x.com/a?p=1.5%');
    });
    it('timestamp ISO a fecha legible', () => {
        assert.match(cleanThesisMarkdown('Dato 2026-10-19T08:30:00Z fin'), /Dato 19 oct 2026 fin/);
        assert.equal(cleanThesisMarkdown('Fecha 2026-10-19 sola'), 'Fecha 2026-10-19 sola');
    });
});
