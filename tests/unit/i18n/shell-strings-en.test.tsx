import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

// Textos fijos de la interfaz que seguían en castellano con English activado:
// esqueletos de carga, salto al contenido, cabecera de Mercados, botones y
// etiquetas sueltas. En castellano no cambia nada.
const mocks = vi.hoisted(() => ({ locale: 'en' }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: mocks.locale }) }) }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock('@/lib/actions/live-quotes.actions', () => ({ getLiveMarkets: async () => null }));
vi.mock('@/components/markets/LiveMarketsPanel', () => ({ LiveMarketsPanel: () => null }));

import { LocaleProvider } from '@/lib/i18n/client';
import RootLoading from '@/app/(root)/loading';
import KnowledgeLoading from '@/app/(root)/knowledge/loading';
import ResearchLoading from '@/app/(root)/research/loading';
import TickerLoading from '@/app/(root)/research/[ticker]/loading';
import WatchlistLoading from '@/app/(root)/watchlist/loading';
import ProPicksLoading from '@/app/(root)/propicks/loading';
import InsiderLoading from '@/app/(root)/insider/loading';
import ScreenersLoading from '@/app/(root)/screeners/loading';
import MercadosPage from '@/app/(root)/mercados/page';
import { FactCalculatedLabel } from '@/components/research/FactCalculatedLabel';
import { DecisionJournalEntryLink } from '@/components/research/DecisionJournalEntryLink';
import { InvestorSelector } from '@/app/(root)/inversores/_components/InvestorSelector';
import { AssistantRedirect } from '@/components/research/AssistantRedirect';
import ThesisMarkdownPager from '@/components/research/ThesisMarkdownPager';
import type { MemoPage } from '@/lib/research/memo-pages';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';

const LOADINGS = [RootLoading, KnowledgeLoading, ResearchLoading, TickerLoading, WatchlistLoading, ProPicksLoading, InsiderLoading, ScreenersLoading];

describe('textos fijos de la interfaz en inglés', () => {
    it('los esqueletos de carga se anuncian en el idioma elegido', async () => {
        for (const Loading of LOADINGS) {
            mocks.locale = 'en';
            const en = renderToStaticMarkup(<LocaleProvider locale="en">{await Loading()}</LocaleProvider>);
            expect(en).toContain('Loading...');
            expect(en).not.toContain('Cargando');
            mocks.locale = 'es';
            expect(renderToStaticMarkup(<LocaleProvider locale="es">{await Loading()}</LocaleProvider>)).toContain('Cargando');
        }
    });

    it('cabecera de Mercados', async () => {
        mocks.locale = 'en';
        const en = render(await MercadosPage());
        expect(screen.getByRole('heading', { name: 'Markets' })).toBeInTheDocument();
        expect(en.container.textContent).toContain('Indices, futures, stocks, commodities and currencies, updated every minute.');
        en.unmount();
        mocks.locale = 'es';
        render(await MercadosPage());
        expect(screen.getByRole('heading', { name: 'Mercados' })).toBeInTheDocument();
        expect(screen.getByText('Índices, futuros, acciones, materias primas y divisas, actualizado cada minuto.')).toBeInTheDocument();
    });

    it('componentes cliente con English', () => {
        render(
            <LocaleProvider locale="en">
                <FactCalculatedLabel fact={{ is_reported: false }} locale="en" />
                <DecisionJournalEntryLink ticker="AAPL" />
                <InvestorSelector investors={[{ slug: 'buffett', name: 'Warren Buffett' }]} />
                <AssistantRedirect ticker="AAPL" />
                <ThesisMarkdownPager pages={[{ id: 'p0', title: 'One', body: 'a' }, { id: 'p1', title: 'Two', body: 'b' }] satisfies MemoPage[]} />
            </LocaleProvider>,
        );
        expect(screen.getByText('Calculated')).toBeInTheDocument();
        expect(screen.getByTestId('decision-journal-entry').textContent).toContain('Decision journal');
        expect(screen.getByRole('combobox', { name: 'Choose an investor' })).toBeInTheDocument();
        expect(screen.getByText(/The research guide now lives in the Brain\./)).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Continue' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Previous' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Next' })).toBeInTheDocument();
    });

    it('en castellano siguen igual', () => {
        render(
            <>
                <FactCalculatedLabel fact={{ is_reported: false }} />
                <DecisionJournalEntryLink ticker="AAPL" />
                <InvestorSelector investors={[]} />
                <ThesisMarkdownPager pages={[{ id: 'p0', title: 'Uno', body: 'a' }, { id: 'p1', title: 'Dos', body: 'b' }] satisfies MemoPage[]} />
            </>,
        );
        expect(screen.getByText('Calculado')).toBeInTheDocument();
        expect(screen.getByTestId('decision-journal-entry').textContent).toContain('Diario de decisiones');
        expect(screen.getByRole('combobox', { name: 'Seleccionar inversor' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Anterior' })).toBeInTheDocument();
    });

    it('el botón de cerrar de los diálogos', () => {
        render(
            <LocaleProvider locale="en">
                <Dialog open>
                    <DialogContent aria-describedby={undefined}><DialogTitle>X</DialogTitle></DialogContent>
                </Dialog>
            </LocaleProvider>,
        );
        expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument();
    });

    it('sin literales en castellano en el marco, el login, la watchlist, insiders y el buscador', () => {
        const read = (path: string) => readFileSync(path, 'utf8');
        expect(read('app/(root)/layout.tsx')).not.toContain('>Saltar al contenido<');
        expect(read('app/(auth)/layout.tsx')).not.toContain('aria-label="Privacidad y condiciones"');
        expect(read('app/(root)/watchlist/page.tsx')).not.toContain('>Precio</dt>');
        expect(read('components/insider/InsiderFeed.tsx')).not.toContain('>Divisa no informada<');
        expect(read('components/SearchCommandDialog.tsx')).not.toContain('heading="Comando"');
    });
});
