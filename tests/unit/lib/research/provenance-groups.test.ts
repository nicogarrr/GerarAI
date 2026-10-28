import { describe, expect, it } from 'vitest';
import { periodoEs, provenanceBasisEs, provenanceGroup } from '@/lib/research/provenance-groups';

describe('provenanceGroup', () => {
    it('dato verificado = reportado; sin verificar se separa; derivado = calculado; resto = supuesto', () => {
        expect(provenanceGroup('dato')).toBe('reportado');
        expect(provenanceGroup('dato', false)).toBe('sin_verificar');
        expect(provenanceGroup('derivado')).toBe('calculado');
        expect(provenanceGroup('supuesto')).toBe('supuesto');
        expect(provenanceGroup(null)).toBe('supuesto');
        expect(provenanceGroup('cualquier cosa', true)).toBe('supuesto');
    });
});

describe('periodoEs', () => {
    it('ejercicio, trimestre, TTM y semestre con fecha de cierre (sin desplazar de día)', () => {
        expect(periodoEs('2025-12-31:FY')).toMatch(/^ejercicio fiscal 2025 \(cierre 31 dic 2025\)$/);
        expect(periodoEs('2026-03-31:Q1')).toMatch(/^T1 2026 \(cierre 31 mar 2026\)$/);
        expect(periodoEs('2026-06-30:TTM')).toMatch(/^últimos doce meses a 30 jun 2026$/);
        expect(periodoEs('2026-06-30:H1')).toMatch(/^H1 2026 \(cierre 30 jun 2026\)$/);
    });
    it('formato no reconocido se devuelve intacto', () => {
        expect(periodoEs('2026-06-30')).toBe('2026-06-30');
        expect(periodoEs('2026-06-30:Q5')).toBe('2026-06-30:Q5');
    });
});

describe('provenanceBasisEs', () => {
    it('vacío -> null', () => {
        expect(provenanceBasisEs(null)).toBeNull();
    });
    it('frases fijas en inglés se traducen', () => {
        expect(provenanceBasisEs('median of latest annual FCF margins')).toBe('Mediana de los últimos márgenes FCF anuales');
        expect(provenanceBasisEs('dado diluted share count CAGR')).toBe('CAGR de las acciones diluidas');
    });
    it('mediana de N observaciones: singular, cero y plural', () => {
        expect(provenanceBasisEs('mediana de las últimas 1 observaciones anuales de market_cap')).toBe('Mediana de la última observación anual de capitalización bursátil');
        expect(provenanceBasisEs('mediana de las últimas 0 observaciones anuales de market_cap')).toBe('Sin observaciones anuales de capitalización bursátil');
        expect(provenanceBasisEs('mediana de las últimas 5 observaciones anuales de metrica_rara')).toBe('Mediana de las últimas 5 observaciones anuales de metrica rara');
    });
    it('variantes ya redactadas', () => {
        expect(provenanceBasisEs('sin observaciones anuales de market_cap')).toBe('Sin observaciones anuales de capitalización bursátil');
        expect(provenanceBasisEs('mediana de la última observación anual de roic')).toMatch(/^Mediana de la última observación anual de /);
    });
    it('reportado con y sin periodo', () => {
        expect(provenanceBasisEs('ingresos reportado')).toBe('Reportado');
        expect(provenanceBasisEs('ingresos reportado (periodo 2025-12-31:FY)')).toContain('Reportado, ejercicio fiscal 2025');
    });
    it('texto libre: primera letra en mayúscula', () => {
        expect(provenanceBasisEs('supuesto del analista')).toBe('Supuesto del analista');
    });
});
