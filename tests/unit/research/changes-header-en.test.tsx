import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChangesSinceVisit } from '@/components/research/ChangesSinceVisit';
import { LocaleProvider } from '@/lib/i18n/client';
import { metricChangeParts } from '@/lib/research/metric-changes';
import { metricLabel } from '@/lib/research/metric-labels';
import en from '@/lib/i18n/messages/en/research.json';

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

afterEach(() => { vi.unstubAllGlobals(); window.localStorage.clear(); window.sessionStorage.clear(); });

describe('changes since your last visit in English', () => {
    beforeEach(() => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json({
            since: '2026-10-01T10:00:00Z',
            documentos: { total: 4, items: [{ titulo: 'Q3 10-Q', tipo: 'filing', url: 'https://sec.gov/a', fecha: null }] },
            hechos: { total: 1, por_metrica: [{ metric: 'market_cap', n: 2 }] },
            cambios_metricas: [{ metric: 'market_cap', unidad: 'USD', anterior: null, nuevo: { valor: 2500000, periodo: 'FY2025' }, fuente: 'SEC' }],
            cambios_tesis: [{ resumen: 'Cambio X.', direccion: 'neg', requiere_revision: true, fecha: '2026-10-02' }],
        })));
    });

    it('banner text, counts and metric names', async () => {
        window.localStorage.setItem('cavaai:last-visit:AAPL', '2026-10-01T10:00:00.000Z');
        render(<LocaleProvider locale="en"><ChangesSinceVisit ticker="AAPL" /></LocaleProvider>);
        await screen.findByRole('region', { name: 'Changes since your last visit' });
        expect(screen.getByText(/^Since your last visit \(/)).toBeInTheDocument();
        expect(screen.getByText(/4 new documents:/)).toBeInTheDocument();
        expect(screen.getByText(/and more/)).toBeInTheDocument();
        expect(screen.getByText(`1 new financial figure (${metricLabel('market_cap', 'en')} ×2)`, { exact: false })).toBeInTheDocument();
        expect(metricLabel('market_cap', 'en')).not.toBe('Capitalización bursátil');
        expect(screen.getByText(/needs review/)).toBeInTheDocument();
        expect(screen.getByRole('list', { name: 'What changed' })).toHaveTextContent('new figure (FY2025) · Source: SEC');
        expect(screen.getByRole('button', { name: 'Mark as read' })).toBeInTheDocument();
        expect(screen.queryByText(/documentos|requiere revisión|Marcar/)).toBeNull();
    });
});

describe('metric change parts in English', () => {
    it('numbers and notes', () => {
        expect(metricChangeParts({ metric: 'm', anterior: { valor: 1234.5, periodo: 'Q1' }, nuevo: { valor: 2500000, periodo: 'Q1' } }, 'en'))
            .toEqual({ before: '1,234.5', after: '2.5M', note: 'Q1, revised' });
        expect(metricChangeParts({ metric: 'm', anterior: null, nuevo: { valor: 3, periodo: 'Q2' } }).note).toBe('dato nuevo (Q2)');
    });
});

describe('price header texts in English', () => {
    it('header keys exist in English', () => {
        expect(en.headerQuote).toMatchObject({ chartClose: 'Last chart close', liveUnavailable: 'Live quote not available right now', previousClose: 'Previous close' });
    });
});
