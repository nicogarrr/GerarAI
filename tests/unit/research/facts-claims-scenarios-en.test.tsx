import { render, screen } from '@testing-library/react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

beforeEach(() => {
    window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
});

import { FactCard, FactTable } from '@/components/research/FactsPanels';
import { ResearchClaimForm } from '@/components/research/ResearchClaimForm';
import { ThesisScenariosPanel } from '@/components/research/ThesisScenariosPanel';
import type { ResearchFact } from '@/lib/actions/research.actions';
import { factDisplayAudit, factStalenessNotice } from '@/lib/research/fact-display-audit';
import es from '@/lib/i18n/messages/es/research.json';
import en from '@/lib/i18n/messages/en/research.json';

const fact: ResearchFact = {
    id: 1, company_id: 1, metric: 'revenue', value: 'x', unit: 'USD', period: 'FY2025', fiscal_year: 2025,
    fiscal_quarter: null, source_id: null, source_type: 'YAHOO_FUNDAMENTALS', is_reported: true, is_adjusted: false,
    confidence: 'high', created_at: '2026-01-01T00:00:00Z', source_url: null, source_title: null, source_published_at: null,
};

const cell = (valor: number | null) => ({ valor, etiqueta: 'INFERIDO', motivo: null });
const scenarios = {
    estado: 'persistido',
    escenarios: {
        bear: { nombre: 'Bear', proyecciones: [{ ejercicio: 2027, ingresos: cell(100), fcf: cell(null), bps: cell(null) }] },
        base: { nombre: 'Base', proyecciones: [{ ejercicio: 2027, ingresos: cell(200), fcf: cell(null), bps: cell(null) }] },
        bull: { nombre: 'Bull', proyecciones: [{ ejercicio: 2027, ingresos: cell(300), fcf: cell(null), bps: cell(null) }] },
    },
    aviso_coherencia: null,
    fuente: { modelo: 'DCF', version: 3, fecha: '2026-10-01' },
} as never;

describe('Hechos financieros, afirmaciones y escenarios de la ficha en inglés', () => {
    it('mismas claves en los dos idiomas', () => {
        for (const area of ['facts', 'claimForm', 'scenarios'] as const) {
            expect(Object.keys(en[area]).sort()).toEqual(Object.keys(es[area]).sort());
        }
    });

    it('tabla de hechos en inglés', () => {
        const html = renderToStaticMarkup(<FactTable facts={[fact]} locale="en" refreshLabel="Refresh" ticker="MSFT" />);
        expect(html).toContain('Includes unofficial figures, unaudited and not checked against the issuer.');
        expect(html).toContain('>Metric<');
        expect(html).toContain('>Period<');
        expect(html).toContain('>Value<');
        expect(html).toContain('unknown');
        expect(html).not.toMatch(/Métrica|desconocido|Hechos financieros/);
        const empty = renderToStaticMarkup(<FactTable facts={[]} locale="en" refreshLabel="Refresh" ticker="MSFT" />);
        expect(empty).toContain('There are no stored financial facts yet.');
        expect(empty).toContain('Press «Refresh» above');
    });

    it('cuarentena y aviso de antigüedad en inglés', () => {
        const card = renderToStaticMarkup(<FactCard fact={{ ...fact, metric: 'market_cap', unit: 'shares' }} locale="en" staleness={null} ticker="MSFT" />);
        expect(card).toContain('N/A');
        expect(card).toContain('Market cap pending audit: currency unit not verified');
        expect(factDisplayAudit('X', { metric: 'eps', unit: 'USD', period: 'FY', value: '1' }, 'en')).toBe('EPS pending audit: unit not verified');
        expect(factStalenessNotice({ metric: 'total_debt', fiscal_year: 2013 }, { isLatestForMetric: true, latestFiscalYear: 2025 }, 'en'))
            .toBe('Latest available figure: 2013, not refreshed since');
    });

    it('alta de afirmaciones y escenarios en inglés', () => {
        render(<ResearchClaimForm action={vi.fn(async () => ({ success: true }))} locale="en" />);
        expect(screen.getByRole('textbox', { name: 'Claim' })).toBeTruthy();
        expect(screen.getByRole('spinbutton', { name: 'Materiality (0 to 10)' })).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Add claim' })).toBeTruthy();
        render(<ThesisScenariosPanel adrRatio={null} currency="USD" data={scenarios} locale="en" />);
        expect(screen.getByText('5-year scenarios')).toBeTruthy();
        expect(screen.getByText('Revenue')).toBeTruthy();
        expect(screen.getAllByText('Fiscal year').length).toBe(3);
        expect(screen.getByText('Model projection DCF v3, as of 2026-10-01.')).toBeTruthy();
    });

    it('en español no cambia', () => {
        const html = renderToStaticMarkup(<FactTable facts={[fact]} refreshLabel="Actualizar" ticker="MSFT" />);
        expect(html).toContain('Incluye cifras no oficiales, sin auditar ni contrastar con el emisor.');
        expect(html).toContain('>Métrica<');
        expect(factDisplayAudit('X', { metric: 'eps', unit: 'USD', period: 'FY', value: '1' })).toBe('BPA pendiente de auditoría: unidad no verificada');
        render(<ThesisScenariosPanel adrRatio={null} currency="USD" data={scenarios} />);
        expect(screen.getByText('Escenarios a 5 años')).toBeTruthy();
        expect(screen.getByText('Proyección del modelo DCF v3, corte 2026-10-01.')).toBeTruthy();
    });
});
