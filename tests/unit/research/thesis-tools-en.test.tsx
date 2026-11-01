import { fireEvent, render, screen } from '@testing-library/react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ run: vi.fn(), getT: vi.fn() }));
vi.mock('@/lib/actions/thesis-jobs.actions', () => ({ runThesisDebate: mocks.run }));
vi.mock('@/lib/i18n/server', () => ({ getT: mocks.getT }));

import TickerNotFound from '@/app/(root)/research/[ticker]/not-found';
import { ParticipationFilingsPanel } from '@/components/research/ParticipationFilingsPanel';
import ThesisAudioPlayer from '@/components/research/ThesisAudioPlayer';
import ThesisDebatePanel from '@/components/research/ThesisDebatePanel';
import ThesisMarkdownPager from '@/components/research/ThesisMarkdownPager';
import { LocaleProvider } from '@/lib/i18n/client';
import { createTranslator } from '@/lib/i18n/translate';
import es from '@/lib/i18n/messages/es/research.json';
import en from '@/lib/i18n/messages/en/research.json';

beforeEach(() => {
    window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ state: 'missing', hasKey: false }) })));
});

const filing = { accession_number: '0002100119-26-001548', form: 'SCHEDULE 13G', holder_name: null, aggregate_shares: 15330194, percent_of_class: 5.11, snapshot_date: null, filing_date: '2026-10-30', source_url: null, status: 'unparsed' };

describe('Audio, debate, memorando, 13D/G y 404 de la ficha en inglés', () => {
    it('mismas claves en los dos idiomas', () => {
        for (const area of ['thesisAudio', 'thesisDebate', 'memoPager', 'participation', 'tickerNotFound'] as const) {
            expect(Object.keys(en[area]).sort()).toEqual(Object.keys(es[area]).sort());
        }
    });

    it('debate y audio en inglés', async () => {
        render(<LocaleProvider locale="en"><ThesisDebatePanel initialVerdict={null} ticker="MSFT" /><ThesisAudioPlayer ticker="MSFT" version={null} /></LocaleProvider>);
        expect(screen.getByRole('button', { name: 'Generate bull/bear debate' })).toBeTruthy();
        expect(screen.getByText(/^Debate not saved yet\./)).toBeTruthy();
        expect(screen.getByRole('group', { name: 'Listen to the thesis' })).toBeTruthy();
        expect(await screen.findByText('No audio: there is no published thesis yet.')).toBeTruthy();
        mocks.run.mockResolvedValue({ ok: false, error: 'timeout' });
        fireEvent.click(screen.getByRole('button', { name: 'Generate bull/bear debate' }));
        expect(await screen.findByText('The debate failed: timeout')).toBeTruthy();
    });

    it('paginador del memorando en inglés', () => {
        render(<LocaleProvider locale="en"><ThesisMarkdownPager pages={[{ title: 'A', markdown: 'a' }, { title: 'B', markdown: 'b' }] as never} /></LocaleProvider>);
        expect(screen.getByRole('button', { name: 'Previous section' })).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Next section' })).toBeTruthy();
        expect(screen.getByLabelText('Memo section')).toBeTruthy();
    });

    it('grandes accionistas en inglés, con números en formato inglés', () => {
        const html = renderToStaticMarkup(<ParticipationFilingsPanel data={{ ticker: 'ASTS', count: 1, filings: [filing] } as never} locale="en" />);
        expect(html).toContain('Major shareholders (13D/G)');
        expect(html).toContain('Filer N/A');
        expect(html).toContain('15,330,194 shares · 5.11%');
        expect(html).toContain('Position as of N/A');
        expect(html).toContain('Filed 2026-10-30');
        expect(html).toContain('Source N/A');
        expect(html).not.toMatch(/acciones|Declarante|Posición/);
    });

    it('404 de la ficha en inglés', async () => {
        mocks.getT.mockResolvedValue(createTranslator('en'));
        render(await TickerNotFound());
        expect(screen.getByRole('heading', { name: 'Stock not found' })).toBeTruthy();
        expect(screen.getByRole('link', { name: 'Back to Research' })).toBeTruthy();
    });

    it('en español no cambia', async () => {
        const html = renderToStaticMarkup(<ParticipationFilingsPanel data={{ ticker: 'ASTS', count: 1, filings: [filing] } as never} />);
        expect(html).toContain('15.330.194 acciones · 5,11 %');
        expect(html).toContain('Declarante N/D');
        mocks.getT.mockResolvedValue(createTranslator('es'));
        render(await TickerNotFound());
        expect(screen.getByRole('heading', { name: 'Acción no encontrada' })).toBeTruthy();
    });
});
