import { readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Guardia de las páginas legales públicas: ningún campo puede quedar sin
 * rellenar. Si vuelve a aparecer un marcador en /privacidad o /terminos,
 * este test falla antes de que el borrador llegue a producción.
 */
const legalPages = ['app/(public)/privacidad/page.tsx', 'app/(public)/terminos/page.tsx'];

describe('páginas legales públicas', () => {
    for (const file of legalPages) {
        it(`${file} no contiene marcadores sin rellenar`, () => {
            const source = readFileSync(path.join(process.cwd(), file), 'utf8');
            expect(source).not.toContain('[PENDIENTE]');
            expect(source).not.toContain('pendingClass');
        });
    }
});
