import { describe, expect, it } from 'vitest';

import { glossary, moatGlossaryKey, moatLabel } from '@/lib/glossary';

describe('moatLabel', () => {
    it('traduce claves canónicas y cortas del backend', () => {
        expect(moatLabel('network_effects')).toBe(glossary.moat_network_effects.term.replace('Moat: ', ''));
        expect(moatLabel('brand')).toBe(moatLabel('intangible_assets'));
        expect(moatLabel('scale')).toBe(moatLabel('scale_economies'));
    });

    it('clave desconocida: fallback legible sin guiones bajos', () => {
        expect(moatLabel('custom_moat_type')).toBe('custom moat type');
    });

    it('claves que coinciden con propiedades de Object no revientan', () => {
        for (const key of ['constructor', 'toString', 'hasOwnProperty', '__proto__']) {
            expect(() => moatLabel(key)).not.toThrow();
            expect(moatLabel(key)).toBe(key.replaceAll('_', ' '));
        }
    });

    it('todas las claves mapeadas existen en el glosario', () => {
        for (const key of Object.values(moatGlossaryKey)) {
            expect(glossary[key]?.term).toMatch(/^Moat: /);
        }
    });
});
