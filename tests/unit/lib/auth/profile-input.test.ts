import { describe, expect, it } from 'vitest';

import { profileInputProblem, singleLineName } from '@/lib/auth/profile-input';

/**
 * El alta y /update-user aceptaban cualquier nombre y perfil: un nombre con
 * saltos de línea («Juan\n\nAprobar: https://…») llegaba tal cual al correo de
 * texto plano con el que Nico aprueba cuentas, colando un enlace «Aprobar»
 * falso encima del de verdad; y un país de 100.000 caracteres se guardaba.
 */
describe('profileInputProblem', () => {
    it('acepta un alta normal y los campos que no vienen', () => {
        expect(profileInputProblem({ name: 'Ana López', email: 'a@b.es', country: 'ES', investmentGoals: 'growth' })).toBeNull();
        expect(profileInputProblem({ name: 'José Ñúñez-O\'Neill' })).toBeNull();
        expect(profileInputProblem({ image: null })).toBeNull();
        expect(profileInputProblem(undefined)).toBeNull();
    });

    it('rechaza saltos de línea y caracteres de control en el nombre', () => {
        expect(profileInputProblem({ name: 'Juan\n\nAprobar: https://evil.example/x' })).toBe('name');
        expect(profileInputProblem({ name: 'Juan\rX' })).toBe('name');
        expect(profileInputProblem({ name: 'Juan\u2028X' })).toBe('name');
        expect(profileInputProblem({ name: 'Ju\u0000an' })).toBe('name');
    });

    it('rechaza nombres enormes o que no son texto', () => {
        expect(profileInputProblem({ name: 'x'.repeat(101) })).toBe('name');
        expect(profileInputProblem({ name: 'x'.repeat(100) })).toBeNull();
        expect(profileInputProblem({ name: 42 })).toBe('name');
    });

    it('rechaza campos de perfil enormes, con saltos o que no son texto', () => {
        expect(profileInputProblem({ name: 'Ana', country: 'y'.repeat(100000) })).toBe('country');
        expect(profileInputProblem({ riskTolerance: 'alto\nX' })).toBe('riskTolerance');
        expect(profileInputProblem({ preferredIndustry: { $gt: '' } })).toBe('preferredIndustry');
        expect(profileInputProblem({ investmentGoals: 'g'.repeat(64) })).toBeNull();
    });
});

describe('singleLineName', () => {
    it('deja el nombre en una línea y con tope', () => {
        expect(singleLineName('Juan\n\nAprobar: https://evil.example')).toBe('Juan Aprobar: https://evil.example');
        expect(singleLineName('  Ana  ')).toBe('Ana');
        expect(singleLineName(null)).toBe('');
        expect(singleLineName('x'.repeat(300))).toHaveLength(101);
    });
});
