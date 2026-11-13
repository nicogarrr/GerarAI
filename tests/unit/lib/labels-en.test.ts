import { describe, expect, it } from 'vitest';

import {
    companyTypeLabel,
    etiquetaDireccionImpacto,
    etiquetaTemaMacro,
    etiquetaTierFuente,
    etiquetaTipoEvento,
    openReviewsLabel,
    tierRankFuente,
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

describe('Cobertura del resto del catalogo', () => {
    it('tiers, direccion de impacto, eventos y temas macro', () => {
        expect(etiquetaTierFuente('tier_3_transcript')).toBe('Transcripción · T3');
        expect(etiquetaTierFuente('tier_3_transcript', 'en')).toBe('Transcript · T3');
        expect(etiquetaTierFuente('tier_9')).toBe('tier_9');
        expect(etiquetaDireccionImpacto('mixed')).toBe('Mixto');
        expect(etiquetaDireccionImpacto('negative', 'en')).toBe('Negative');
        expect(etiquetaDireccionImpacto('sideways')).toBe('sideways');
        expect(etiquetaTipoEvento('earnings')).toBe('Resultados');
        expect(etiquetaTipoEvento('regulatory', 'en')).toBe('Regulatory');
        expect(etiquetaTipoEvento('ipo')).toBe('ipo');
        expect(etiquetaTemaMacro('interest_rates')).toBe('Tipos de interés');
        expect(etiquetaTemaMacro('interest_rates', 'en')).toBe('Interest rates');
        expect(etiquetaTemaMacro('new_theme')).toBe('new_theme');
    });

    it('orden de tiers: primarias primero, desconocidas al final', () => {
        expect(tierRankFuente('tier_1_regulatory')).toBe(0);
        expect(tierRankFuente('tier_8_social')).toBe(7);
        expect(tierRankFuente('tier_unknown')).toBe(8);
        expect(tierRankFuente('tier_2_company')).toBeLessThan(tierRankFuente('tier_7_user_input'));
    });

    it('sector e industria: colapso, solo industria y passthrough', () => {
        expect(etiquetaSector('Financial Services')).toBe('Servicios financieros');
        expect(etiquetaSector('Biotecnologia X')).toBe('Biotecnologia X');
        expect(sectorIndustryLine('Technology', 'Technology')).toBe('Tecnología');
        expect(sectorIndustryLine(null, 'Software')).toBe('Software');
        expect(sectorIndustryLine(null, null)).toBe('Sector sin dato');
        expect(sectorIndustryLine(null, null, 'en')).toBe('Sector not available');
        expect(sectorIndustryLine('unknown', ' ')).toBe('Sector sin dato');
    });

    it('severidad insensible a mayusculas, instrumento y atribucion honestos', () => {
        expect(etiquetaSeveridad('CRITICAL')).toBe('Crítica');
        expect(etiquetaSeveridad('weird')).toBe('weird');
        expect(etiquetaTipoInstrumento('Warrant')).toBe('Warrant');
        expect(etiquetaComponenteAtribucion('new_comp')).toBe('new_comp');
    });

    it('tipo de empresa: pares de factores y desconocido tal cual', () => {
        expect(companyTypeLabel('ai_biology_china')).toBe('IA aplicada a biología · China');
        expect(companyTypeLabel('zzz_qqq')).toBe('zzz_qqq');
        expect(etiquetaFactor('ads')).toBe('Publicidad');
        expect(etiquetaFactor('new thing')).toBe('New thing');
    });

    it('pendientes de revision y valores sueltos', () => {
        expect(openReviewsLabel(null)).toBeNull();
        expect(openReviewsLabel({ open_reviews: 0, open_alerts: 0 })).toBeNull();
        expect(openReviewsLabel({ open_reviews: 1 })).toBe('1 revisión abierta');
        expect(openReviewsLabel({ open_alerts: 2 })).toBe('2 alertas abiertas');
        expect(openReviewsLabel({ open_reviews: 2, open_alerts: 1 })).toBe('2 revisiones abiertas · 1 alerta abierta');
        expect(etiquetaValor('tier_1_regulatory')).toBe('Regulatoria · T1');
        expect(etiquetaValor('brand_new')).toBe('brand new');
    });
});
