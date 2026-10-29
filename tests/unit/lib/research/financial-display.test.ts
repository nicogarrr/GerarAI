import { describe, expect, it } from 'vitest';
import {
    financialDefinition, financialFormula, financialPeriod, financialSegment, financialVersion, financialVersionLabel, loadedFinancialRange,
} from '@/lib/research/financial-display';

describe('financialPeriod', () => {
    it('desconocido, con fecha (FY y trimestres) y formatos antiguos', () => {
        expect(financialPeriod('unknown')).toBe('Periodo no informado por la fuente');
        expect(financialPeriod('2025-12-31:FY')).toBe('Ejercicio al 31/12/2025');
        expect(financialPeriod('2026-03-31:Q1')).toBe('T1 al 31/03/2026');
        expect(financialPeriod('FY2025')).toBe('Ejercicio 2025');
        expect(financialPeriod('Q3 2025')).toBe('T3 2025');
        expect(financialPeriod('2026-03-31:TTM')).toBe('2026-03-31:TTM');
    });
});

describe('financialFormula', () => {
    it('traduce frases conocidas y palabras con etiqueta; deja lo desconocido', () => {
        expect(financialFormula('count of passed checks: 5')).toBe('número de criterios superados: 5');
        expect(financialFormula('mean of annual tax_rate')).toBe('media anual de tipo impositivo');
        expect(financialFormula('zzz_desconocido plus abc')).toBe('zzz_desconocido más abc');
    });
    it('las frases largas ganan a las palabras sueltas (orden de reemplazo)', () => {
        expect(financialFormula('approximate CFROI: x where y')).toBe('CFROI aproximado: x donde y');
    });
});

describe('definiciones y versiones', () => {
    it('definición exacta, o cae a la fórmula traducida', () => {
        expect(financialDefinition('Gross Margin')).toBe('Margen bruto');
        expect(financialDefinition('Stock-based compensation expense.')).toBe('Gasto de remuneración en acciones.');
        expect(financialDefinition('plus nada')).toBe('más nada');
    });
    it('segmento', () => {
        expect(financialSegment('consolidated')).toBe('Consolidado');
        expect(financialSegment('Cloud')).toBe('Cloud');
    });
    it('versiones: conocida, patrón _Vn y sin versión', () => {
        expect(financialVersion('MARCO_V2')).toBe('Marco de calidad · versión 2');
        expect(financialVersion('OTRA')).toBe('OTRA');
        expect(financialVersionLabel('MARCO_V1')).toBe('Marco de calidad · versión 1');
        expect(financialVersionLabel('CFROI_V3')).toBe('cálculo v3');
        expect(financialVersionLabel('cfroi')).toBe('cálculo sin versión');
    });
});

describe('loadedFinancialRange', () => {
    const m = (series: Array<{ period: string; value: string | number | null }>) => ({ series });
    it('rango de años solo con valores presentes (un periodo sin valor no cuenta)', () => {
        expect(loadedFinancialRange([m([{ period: '2020-12-31:FY', value: 1 }, { period: 'FY2019', value: null }]), m([{ period: '2023-03-31:Q1', value: 0 }])])).toBe('2020–2023');
    });
    it('un solo año, sin datos y periodos de formato raro', () => {
        expect(loadedFinancialRange([m([{ period: 'FY2024', value: 2 }])])).toBe('2024');
        expect(loadedFinancialRange([m([{ period: '2024-12-31:FY', value: null }])])).toBeNull();
        expect(loadedFinancialRange([m([{ period: 'unknown', value: 1 }])])).toBeNull();
        expect(loadedFinancialRange([])).toBeNull();
    });
});


describe('fórmulas owner earnings versión 2', () => {
    it('traduce la convención de signo sin cambiar operadores ni el límite de mantenimiento', () => {
        const formula = 'net_income + depreciation_amortization + change_in_working_capital - maintenance_capex, where change_in_working_capital is in cash-flow sign (negative = working capital absorbed cash) and maintenance_capex = min(abs(capital_expenditure), depreciation_amortization); maintenance capex is not separately reported - declared conservative estimate (Buffett owner earnings, Berkshire Hathaway 1986 letter)';
        const text = financialFormula(formula);
        expect(text).toContain('negativo = el capital circulante absorbió efectivo');
        expect(text).toContain('carta de Berkshire Hathaway de 1986');
        expect(text).toContain('mínimo(valor absoluto(');
        expect(text).not.toMatch(/cash-flow|working capital|is not separately|declared conservative/);
        expect(text).toContain(' + ');
        expect(text).toContain(' - ');
    });
    it('traduce la media de varios años manteniendo cobertura mínima y signo', () => {
        const text = financialFormula('mean of annual (net_income + depreciation_amortization + change_in_working_capital - min(abs(capital_expenditure), depreciation_amortization)) over up to 5 most recent fiscal years, minimum 3; change_in_working_capital in cash-flow sign; maintenance capex is a declared conservative estimate (Buffett owner earnings, Berkshire Hathaway 1986 letter)');
        expect(text).toContain('un mínimo de 3');
        expect(text).toContain('con el signo del flujo de caja');
        expect(text).not.toMatch(/cash-flow|maintenance capex|declared conservative/);
    });
});
