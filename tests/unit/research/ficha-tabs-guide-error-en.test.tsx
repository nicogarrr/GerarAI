import { render, screen } from '@testing-library/react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import RootError from '@/app/(root)/error';
import { CompanyNavigation } from '@/components/research/CompanyNavigation';
import { GuideContextPanel } from '@/components/research/GuideContextPanel';
import { LocaleProvider } from '@/lib/i18n/client';
import esUi from '@/lib/i18n/messages/es/ui.json';
import enUi from '@/lib/i18n/messages/en/ui.json';
import es from '@/lib/i18n/messages/es/research.json';
import en from '@/lib/i18n/messages/en/research.json';

const context = { open_reviews: [], latest_news: [], missing_data: ['precio'] } as never;

beforeEach(() => {
    window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
});

describe('Pestañas de la ficha, guía y pantalla de error en inglés', () => {
    it('mismas claves en los dos idiomas', () => {
        expect(Object.keys(enUi.rootError).sort()).toEqual(Object.keys(esUi.rootError).sort());
        expect(Object.keys(en.guideContext).sort()).toEqual(Object.keys(es.guideContext).sort());
        expect(Object.keys(en.companyNav)).toEqual(Object.keys(es.companyNav));
        expect(Object.keys(en.tabs)).toEqual(Object.keys(es.tabs));
    });

    it('las seis pestañas de la ficha en inglés, mismas URLs', () => {
        expect(Object.values(en.tabs)).toEqual(['Overview', 'Thesis', 'Financials', 'Valuation', 'Tracking', 'Sources']);
        const html = renderToStaticMarkup(<CompanyNavigation activeView="overview" locale="en" ticker="MSFT" />);
        expect(html).toContain('aria-label="Company sections"');
        expect(html).toContain('>Valuation<');
        expect(html).toContain('view=valoracion');
        expect(html).not.toContain('Valoración');
    });

    it('guía de investigación en inglés', () => {
        render(<LocaleProvider locale="en"><GuideContextPanel context={context} ticker="MSFT" /></LocaleProvider>);
        expect(screen.getByText('Research guide')).toBeTruthy();
        expect(screen.getByText('No open reviews.')).toBeTruthy();
        expect(screen.getByText('No news data.')).toBeTruthy();
        expect(screen.getByText('Data missing from the context')).toBeTruthy();
    });

    it('pantalla de error en inglés', () => {
        vi.spyOn(console, 'error').mockImplementation(() => {});
        render(<LocaleProvider locale="en"><RootError error={Object.assign(new Error('fetch failed'), { digest: 'abc' })} reset={vi.fn()} /></LocaleProvider>);
        expect(screen.getByRole('heading', { name: "The operation couldn't be completed" })).toBeTruthy();
        expect(screen.getByText(/^The data engine isn't available right now/)).toBeTruthy();
        expect(screen.getByText('Reference: abc')).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy();
    });

    it('en español no cambia', () => {
        const html = renderToStaticMarkup(<CompanyNavigation activeView="overview" ticker="MSFT" />);
        expect(html).toContain('aria-label="Secciones de la empresa"');
        expect(html).toContain('>Valoración<');
        vi.spyOn(console, 'error').mockImplementation(() => {});
        render(<RootError error={new Error('boom')} reset={vi.fn()} />);
        expect(screen.getByRole('heading', { name: 'No se pudo completar la operación' })).toBeTruthy();
        expect(screen.getByText('Se produjo un error inesperado. Inténtalo de nuevo.')).toBeTruthy();
    });
});
