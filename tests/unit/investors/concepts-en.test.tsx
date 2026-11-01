import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ locale: 'en' }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: mocks.locale }) }) }));
vi.mock('next/navigation', () => ({ notFound: () => { throw Error('NOT_FOUND'); }, usePathname: () => '/inversores/conceptos' }));
vi.mock('next/link', () => ({ default: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props}>{children}</a> }));

import ConceptsPage from '@/app/(root)/inversores/conceptos/page';
import ConceptPage from '@/app/(root)/inversores/conceptos/[slug]/page';
import { OptionPayoff } from '@/app/(root)/inversores/conceptos/OptionPayoff';
import { InvestorConcepts } from '@/app/(root)/inversores/_components/InvestorConcepts';
import { CONCEPTS } from '@/app/(root)/inversores/conceptos/concepts';
import { conceptsFor } from '@/app/(root)/inversores/conceptos/concepts-i18n';
import { LocaleProvider } from '@/lib/i18n/client';

const withLocale = (ui: React.ReactNode) => render(<LocaleProvider locale={mocks.locale as 'es' | 'en'}>{ui}</LocaleProvider>);

describe('Conceptos de inversión en inglés', () => {
    it('cada concepto tiene su versión inglesa y el español no cambia', () => {
        const en = conceptsFor('en');
        expect(en).toHaveLength(CONCEPTS.length);
        en.forEach((concept, index) => {
            const es = CONCEPTS[index];
            expect(concept.slug).toBe(es.slug);
            expect(concept.source.url).toBe(es.source.url);
            for (const field of ['summary', 'body', 'application', 'risk'] as const) expect(concept[field]).not.toBe(es[field]);
        });
        expect(conceptsFor('es')).toEqual(CONCEPTS);
    });

    it('la lista de conceptos sale en inglés', async () => {
        mocks.locale = 'en';
        withLocale(await ConceptsPage({ searchParams: Promise.resolve({}) }));
        expect(screen.getByRole('heading', { level: 1, name: 'Concepts' })).toBeTruthy();
        expect(screen.getByRole('heading', { name: 'Circle of competence' })).toBeTruthy();
        expect(screen.getAllByText('Berkshire Hathaway · 1996 letter').length).toBeGreaterThan(0);
    });

    it('la ficha de un concepto y el gráfico de opciones salen en inglés', async () => {
        mocks.locale = 'en';
        // El gráfico es un componente servidor asíncrono: se pinta aparte.
        withLocale(await ConceptPage({ params: Promise.resolve({ slug: 'wacc' }) }));
        expect(screen.getByRole('heading', { level: 1, name: 'WACC (weighted average cost of capital)' })).toBeTruthy();
        expect(screen.getByRole('heading', { name: 'How to apply it' })).toBeTruthy();
        expect(screen.getByRole('heading', { name: 'Risk' })).toBeTruthy();
        expect(screen.getByText(/^Editorial summary/)).toBeTruthy();
        withLocale(await OptionPayoff());
        expect(screen.getByRole('region', { name: 'Hypothetical example of buying options' })).toBeTruthy();
        expect(screen.getByText('Long call')).toBeTruthy();
        expect(screen.getByText('Underlying price')).toBeTruthy();
    });

    it('los conceptos de la ficha del inversor salen en inglés; en español no cambian', async () => {
        mocks.locale = 'en';
        const en = withLocale(await InvestorConcepts({ slug: 'buffett' }));
        expect(screen.getByRole('heading', { name: 'Concepts' })).toBeTruthy();
        expect(screen.getByText('See all')).toBeTruthy();
        expect(screen.getByText('Economic moat')).toBeTruthy();
        en.unmount();
        mocks.locale = 'es';
        withLocale(await InvestorConcepts({ slug: 'munger' }));
        expect(screen.getByText('Sin conceptos documentados para este inversor')).toBeTruthy();
    });
});
