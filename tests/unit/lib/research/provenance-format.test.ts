import { describe, expect, it } from 'vitest';
import { capitalizeLabel, formatMoneyShort, formatProvenanceValue } from '@/lib/research/provenance-format';

describe('formatProvenanceValue', () => {
    it('sin dato: N/D; texto no numérico se devuelve recortado, no se inventa número', () => {
        expect(formatProvenanceValue(null, 'USD')).toBe('N/D');
        expect(formatProvenanceValue(undefined)).toBe('N/D');
        expect(formatProvenanceValue('', 'USD')).toBe('N/D');
        expect(formatProvenanceValue('  n/a  ')).toBe('n/a');
        expect(formatProvenanceValue(Infinity)).toBe('N/D');
    });
    it('unidad decimal/ratio: fracción -> porcentaje con coma', () => {
        expect(formatProvenanceValue(0.144, 'decimal')).toMatch(/^14,4\s?%$/);
        expect(formatProvenanceValue('0.5', 'ratio')).toMatch(/^50,0\s?%$/);
    });
    it('unidad %: el valor ya es porcentaje (25 -> 25,0 %), no se multiplica por 100', () => {
        expect(formatProvenanceValue(25, '%')).toMatch(/^25,0\s?%$/);
        expect(formatProvenanceValue(-3.25, 'pct')).toMatch(/^-3,3\s?%$|^-3,2\s?%$/);
    });
    it('separador de miles en texto "1,234.5" se interpreta', () => {
        expect(formatProvenanceValue('1,234.5', '')).toBe('1234,5');
    });
    it('divisa declarada: respeta la divisa, nunca la cambia', () => {
        expect(formatProvenanceValue(14.4, 'EUR')).toBe('€14.40');
        expect(formatProvenanceValue(1234, 'USD')).toBe('$1,234');
        expect(formatProvenanceValue(4_870_000_000, 'EUR')).toBe('€4.87B');
    });
    it('un código de 3 letras que no es divisa no se trata como dinero', () => {
        const out = formatProvenanceValue(5, 'ZZZ');
        expect(out).not.toMatch(/[$€]/);
    });
    it('unidades sin dimensión: solo el número', () => {
        expect(formatProvenanceValue(3.14159, 'pure')).toBe('3,14');
        expect(formatProvenanceValue(1500, 'count')).toBe('1500');
        expect(formatProvenanceValue(2_500_000, 'units')).toMatch(/2,5\s?M/);
    });
    it('X_per_unit y acciones', () => {
        expect(formatProvenanceValue(12, 'usd_per_unit')).toBe('12 USD por unidad');
        expect(formatProvenanceValue(1000, 'shares')).toBe('1000 acciones');
        expect(formatProvenanceValue(1, 'share')).toBe('1 acción');
        expect(formatProvenanceValue(7, 'widgets')).toBe('7 widgets');
    });
    it('sin unidad: número tal cual, sin símbolo ni %', () => {
        expect(formatProvenanceValue(0.3333333)).toBe('0,33');
    });
});

describe('formatMoneyShort', () => {
    it('USD >= 1e6 usa la escala de capitalización', () => {
        expect(formatMoneyShort(4_870_000_000, 'USD')).toBe('$4.87B');
    });
    it('menos de 100: 2 decimales; 100 o más: sin decimales', () => {
        expect(formatMoneyShort(14.4, 'EUR')).toBe('€14.40');
        expect(formatMoneyShort(150.6, 'EUR')).toBe('€151');
    });
    it('negativos conservan el signo', () => {
        expect(formatMoneyShort(-14.4, 'EUR')).toBe('-€14.40');
    });
    it('millones en otra divisa: compacto con 2 decimales', () => {
        expect(formatMoneyShort(2_000_000, 'EUR')).toBe('€2.00M');
    });
});

describe('capitalizeLabel', () => {
    it('capitaliza y recorta; vacío sigue vacío', () => {
        expect(capitalizeLabel('  ingresos ')).toBe('Ingresos');
        expect(capitalizeLabel('   ')).toBe('');
    });
});
