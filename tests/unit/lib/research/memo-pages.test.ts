import { describe, expect, it } from 'vitest';
import { splitMemoPages } from '@/lib/research/memo-pages';
import { factDisplayAudit, factStalenessNotice } from '@/lib/research/fact-display-audit';
import { isVerifiedOficial, provenanceUrls, type ProvenanceItem } from '@/lib/research/provenance-item';
import { safeAssistantSourceUrl } from '@/lib/research/assistant-contract';
import { formatScenarioMoney, scenarioCurrency } from '@/lib/research/scenario-format';

describe('splitMemoPages', () => {
    it('vacío -> sin páginas', () => {
        expect(splitMemoPages('')).toEqual([]);
        expect(splitMemoPages('  \n ')).toEqual([]);
    });
    it('divide por ## y limpia numeración y formato del título', () => {
        const pages = splitMemoPages('# Memo\n\n## 1. **Resumen**\ntexto A\n## 2) Riesgos\ntexto B');
        expect(pages.map((p) => p.title)).toEqual(['Resumen', 'Riesgos']);
        expect(pages[0].id).toBe('p0');
        expect(pages[0].body).toContain('texto A');
        expect(pages[1].body).not.toContain('texto A');
    });
    it('el preámbulo se pega a la primera sección (sin el H1)', () => {
        const [first] = splitMemoPages('# Título\nintro\n## Uno\ncuerpo');
        expect(first.body).toContain('intro');
        expect(first.body).not.toContain('# Título');
    });
    it('secciones vacías (solo encabezado) se descartan', () => {
        expect(splitMemoPages('## Vacía\n## Llena\ncontenido').map((p) => p.title)).toEqual(['Llena']);
    });
    it('sin ningún ##: una sola página con el H1 como título, o "Memo"', () => {
        expect(splitMemoPages('# Mi **memo**\ncuerpo')).toEqual([{ id: 'p0', title: 'Mi memo', body: '# Mi **memo**\ncuerpo' }]);
        expect(splitMemoPages('solo texto')[0].title).toBe('Memo');
    });
    it('no pierde contenido cuando todas las secciones están vacías pero hay texto', () => {
        expect(splitMemoPages('## A\n## B')[0].body).toContain('## A');
    });
});

describe('factDisplayAudit', () => {
    const fact = { metric: 'eps_diluted', unit: 'USD/share', period: '2025-12-31:FY', value: '1.2' };
    it('solo audita BPA; el resto pasa', () => {
        expect(factDisplayAudit('X', { ...fact, metric: 'revenue', unit: 'bad' })).toBeNull();
    });
    it('BPA con unidad no verificada se marca', () => {
        expect(factDisplayAudit('X', { ...fact, unit: 'USD' })).toMatch(/unidad no verificada/);
        expect(factDisplayAudit('X', { ...fact, metric: 'eps', unit: 'usd/share' })).toMatch(/unidad no verificada/);
        expect(factDisplayAudit('X', fact)).toBeNull();
        expect(factDisplayAudit('X', { ...fact, unit: 'EUR/shares' })).toBeNull();
    });
    it('caso conocido ASTS sin linaje', () => {
        const bad = { ...fact, period: '2020-03-31:Q1', value: '17600000' };
        expect(factDisplayAudit('asts', bad)).toMatch(/sin linaje/);
        expect(factDisplayAudit('MSFT', bad)).toBeNull();
        expect(factDisplayAudit('ASTS', { ...bad, value: '17600001' })).toBeNull();
    });
});

describe('factStalenessNotice', () => {
    const f = { metric: 'total_debt', fiscal_year: 2022 };
    it('dato de balance con más de un año de retraso respecto al último', () => {
        expect(factStalenessNotice(f, { isLatestForMetric: true, latestFiscalYear: 2025 })).toBe('Último dato disponible: 2022, sin refresco posterior');
    });
    it('un año de diferencia, no último, métrica de flujo o fechas ausentes: sin aviso', () => {
        expect(factStalenessNotice(f, { isLatestForMetric: true, latestFiscalYear: 2023 })).toBeNull();
        expect(factStalenessNotice(f, { isLatestForMetric: false, latestFiscalYear: 2025 })).toBeNull();
        expect(factStalenessNotice({ metric: 'revenue', fiscal_year: 2020 }, { isLatestForMetric: true, latestFiscalYear: 2025 })).toBeNull();
        expect(factStalenessNotice({ ...f, fiscal_year: null }, { isLatestForMetric: true, latestFiscalYear: 2025 })).toBeNull();
        expect(factStalenessNotice(f, { isLatestForMetric: true, latestFiscalYear: null })).toBeNull();
    });
});

describe('provenance-item', () => {
    const src = { oficial: true, fecha: '2026-01-01', url: 'https://sec.gov/x' };
    const item = (over: Record<string, unknown>) => ({ origen: 'OFICIAL', fuentes: [src], ...over }) as unknown as ProvenanceItem;
    it('oficial verificado: todas las fuentes oficiales, con fecha y https', () => {
        expect(isVerifiedOficial(item({}))).toBe(true);
        expect(isVerifiedOficial(item({ origen: 'INFERIDO' }))).toBe(false);
        expect(isVerifiedOficial(item({ fuentes: [] }))).toBe(false);
        expect(isVerifiedOficial(item({ fuentes: undefined }))).toBe(false);
        expect(isVerifiedOficial(item({ fuentes: [src, { ...src, oficial: false }] }))).toBe(false);
        expect(isVerifiedOficial(item({ fuentes: [{ ...src, fecha: '' }] }))).toBe(false);
        expect(isVerifiedOficial(item({ fuentes: [{ ...src, url: 'http://sec.gov/x' }] }))).toBe(false);
    });
    it('urls: solo https, sin duplicados, incluye las de inferencia', () => {
        const urls = provenanceUrls(item({ fuentes: [src, { ...src, url: 'http://x.com' }, { ...src, url: 'https://sec.gov/x' }], urls_inferencia: ['https://b.com', 'javascript:alert(1)', null] }));
        expect(urls).toEqual(['https://sec.gov/x', 'https://b.com']);
        expect(provenanceUrls(item({ fuentes: undefined }))).toEqual([]);
    });
});

describe('safeAssistantSourceUrl', () => {
    it('solo http(s) sin credenciales', () => {
        expect(safeAssistantSourceUrl('https://sec.gov/a?b=1')).toBe('https://sec.gov/a?b=1');
        expect(safeAssistantSourceUrl('http://x.com')).toBe('http://x.com/');
        for (const bad of ['javascript:alert(1)', 'data:text/html,x', 'https://user:pw@x.com', 'https://user@x.com', 'ftp://x.com', 'no es url', '', null, undefined]) {
            expect(safeAssistantSourceUrl(bad as never)).toBeNull();
        }
    });
});

describe('scenario-format', () => {
    it('divisa válida de 3 letras; ADR o código raro: sin divisa (no se inventa)', () => {
        expect(scenarioCurrency(' usd ', null)).toEqual({ code: 'USD' });
        expect(scenarioCurrency('USD', 2)).toBeNull();
        expect(scenarioCurrency('US', null)).toBeNull();
        expect(scenarioCurrency(null, null)).toBeNull();
    });
    it('formato: null sin valor, sin divisa o no finito; USD en inglés compacto', () => {
        expect(formatScenarioMoney(null, { code: 'USD' }, 2)).toBeNull();
        expect(formatScenarioMoney(5, null, 2)).toBeNull();
        expect(formatScenarioMoney(NaN, { code: 'USD' }, 2)).toBeNull();
        expect(formatScenarioMoney(12.5, { code: 'USD' }, 2)).toBe('$12.50');
        expect(formatScenarioMoney(2_500_000_000, { code: 'USD' }, 1)).toBe('$2.5B');
        expect(formatScenarioMoney(12.5, { code: 'EUR' }, 2)).toMatch(/12,50/);
    });
});
