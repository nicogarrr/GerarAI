import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { themeMethodText } from '@/lib/market/theme-method-text';
import { createTranslator } from '@/lib/i18n/translate';

// Valores reales de market_themes.py («method»), leídos del .py: si cambian, el test lo nota.
const PY = readFileSync('data-engine/app/services/market_themes.py', 'utf8');
const METHODS = [...new Set([...PY.matchAll(/"method": "([^"]+)"/g)].map((m) => m[1]))];
const PAGE = readFileSync('app/(root)/temas/page.tsx', 'utf8');

describe('Temas: método del pie en el idioma de la pantalla', () => {
    it('lee el método del backend', () => {
        expect(METHODS).toEqual(['media simple']);
    });

    it('en inglés, «simple average»', () => {
        expect(METHODS.map((m) => themeMethodText(m, createTranslator('en')))).toEqual(['simple average']);
    });

    it('en castellano, tal cual', () => {
        expect(METHODS.map((m) => themeMethodText(m, createTranslator('es')))).toEqual(METHODS);
    });

    it('otro texto pasa tal cual', () => {
        expect(themeMethodText('market-cap weighted', createTranslator('en'))).toBe('market-cap weighted');
    });

    it('el pie de la página ya no pinta el método crudo', () => {
        expect(PAGE).not.toMatch(/\$\{data\.method\}/);
        expect(PAGE).toMatch(/themeMethodText\(data\.method, t\)/);
    });
});
