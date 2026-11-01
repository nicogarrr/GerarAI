import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { LocaleProvider } from '@/lib/i18n/client';
import { Pager } from '@/components/research/Pager';

const i18n = vi.hoisted(() => ({ locale: 'en' as 'es' | 'en' }));
vi.mock('@/lib/i18n/server', async () => {
    const { createTranslator } = await import('@/lib/i18n/translate');
    return { getLocale: async () => i18n.locale, getT: async () => createTranslator(i18n.locale) };
});
vi.mock('@/lib/actions/research.actions', () => ({
    getResearchSources: vi.fn(async () => ({
        documents: [{ id: 1, ticker: 'AAPL', title: '10-K 2025', source_type: 'filing', source_tier: 'tier_1_regulatory', published_at: null, source_url: 'https://www.sec.gov/x' }],
        audits: [], documentsTotal: 1, pageInfo: { page: 1, pages: 1, from: 1, to: 1 },
    })),
    importResearchDocumentFile: vi.fn(), importResearchDocumentUrl: vi.fn(), importResearchSource: vi.fn(),
}));
vi.mock('@/components/search/TickerSearchInput', () => ({ TickerSearchInput: () => null }));
vi.mock('@/components/forms/FileUploadInputLazy', () => ({ FileUploadInputLazy: () => null }));
vi.mock('@/components/forms/MutationForm', () => ({ MutationForm: ({ children }: { children: React.ReactNode }) => <form>{children}</form> }));
import ResearchSourcesPage from '@/app/(root)/research/sources/page';

const page = () => ResearchSourcesPage({ searchParams: Promise.resolve({}) } as never);

describe('fuentes y paginador en inglés', () => {
    it('la página de fuentes sale en inglés', async () => {
        i18n.locale = 'en';
        render(await page());
        expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Sources');
        expect(screen.getAllByText('Regulatory filing').length).toBeGreaterThan(1);
        expect(screen.getByText('no date')).toBeInTheDocument();
        expect(screen.getByText('No audits yet.')).toBeInTheDocument();
        expect(screen.getByText('Add sources')).toBeInTheDocument();
        expect(screen.queryByText(/Documentos|Auditorías|Añadir fuentes|sin fecha/)).not.toBeInTheDocument();
    });
    it('en español no cambia', async () => {
        i18n.locale = 'es';
        render(await page());
        expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Fuentes');
        expect(screen.getAllByText('Documento regulatorio').length).toBeGreaterThan(0);
        expect(screen.getByText('Sin auditorías todavía.')).toBeInTheDocument();
    });
    it('el paginador compartido sigue el idioma', () => {
        render(<LocaleProvider locale="en"><Pager label="documents" onPage={() => undefined} page={1} pages={3} total={30} /></LocaleProvider>);
        expect(screen.getByRole('navigation', { name: 'Pagination: documents' })).toBeInTheDocument();
        expect(screen.getByText('Page 1 of 3')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Next' })).toBeInTheDocument();
    });
    it('el paginador en español no cambia', () => {
        render(<Pager label="documentos" onPage={() => undefined} page={2} pages={3} total={30} />);
        expect(screen.getByRole('navigation', { name: 'Paginación de documentos' })).toBeInTheDocument();
        expect(screen.getByText('Página 2 de 3')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Anterior' })).toBeInTheDocument();
    });
});
