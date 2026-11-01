import { describe, expect, it } from 'vitest';

import {
    companyTypeLabel,
    etiquetaComponenteAtribucion,
    etiquetaFactor,
    etiquetaSector,
    etiquetaSeveridad,
    etiquetaTipoInstrumento,
    etiquetaValor,
    sectorIndustryLine,
} from '@/lib/labels';

describe('Etiquetas financieras en inglés', () => {
    it('sector e industria: originales en inglés, traducidos en español', () => {
        expect(sectorIndustryLine('Technology', 'Semiconductor Equipment', 'en')).toBe('Technology · Semiconductor Equipment');
        expect(sectorIndustryLine('Unknown', null, 'en')).toBe('Sector not available');
        expect(sectorIndustryLine('Unknown', null)).toBe('Sector sin dato');
        expect(sectorIndustryLine('Technology', 'Semiconductor Equipment')).toBe(`${etiquetaSector('Technology')} · Equipos de semiconductores`);
        expect(etiquetaSector('Technology', 'en')).toBe('Technology');
    });

    it('severidad, factores, tipo de empresa y atribución', () => {
        expect(etiquetaSeveridad('HIGH', 'en')).toBe('High');
        expect(etiquetaSeveridad('high')).toBe('Alta');
        expect(etiquetaFactor('cloud', 'en')).toBe('Cloud');
        expect(etiquetaFactor('cloud')).toBe('Nube');
        expect(etiquetaFactor('adr:2', 'en')).toBe('ADR (ratio 2)');
        expect(companyTypeLabel('software_durable_growth', 'en')).toBe('durable-growth software');
        expect(companyTypeLabel('ai_cloud', 'en')).toBe('AI · Cloud');
        expect(companyTypeLabel('ai_cloud')).toBe('IA · Nube');
        expect(etiquetaComponenteAtribucion('buybacks', 'en')).toBe('Buybacks');
        expect(etiquetaComponenteAtribucion('buybacks')).toBe('Recompras');
    });

    it('valores del backend y tipo de instrumento', () => {
        expect(etiquetaValor('sec_filing', 'en')).toBe('SEC filing');
        expect(etiquetaValor('sec_filing')).toBe('informe SEC');
        expect(etiquetaValor('something_new', 'en')).toBe('something new');
        expect(etiquetaTipoInstrumento('Common Stock', 'en')).toBe('Common Stock');
        expect(etiquetaTipoInstrumento('Common Stock')).toBe('Acción ordinaria');
    });
});
