import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ locale: 'en' }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: mocks.locale }) }) }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => '/inversores/buffett' }));

import { Portfolio } from '@/app/(root)/inversores/_components/Portfolio';
import { PublicProfileSection } from '@/app/(root)/inversores/_components/PublicProfile';
import { InvestorViewSelector } from '@/app/(root)/inversores/_components/InvestorViewSelector';
import type { InvestorPortfolio, PublicProfile } from '@/lib/actions/investors.actions';
import { LocaleProvider } from '@/lib/i18n/client';

const withLocale = (ui: React.ReactNode) => render(<LocaleProvider locale={mocks.locale as 'es' | 'en'}>{ui}</LocaleProvider>);
const datum = (value: number | null) => ({ value, label: value === null ? 'SIN_DATOS' : 'OFICIAL', as_of: '2026-06-30', source_url: 'https://sec.test' });
const portfolio = {
    slug: 'buffett', as_of: '2026-06-30', coverage: 'partial', limitations: null, total_value_usd: datum(1_000_000_000),
    positions: [{ issuer: 'Apple Inc', ticker: 'AAPL', cusip: '1', title_of_class: 'COM', source_form: '13F', value_usd: datum(250_000_000), weight_pct: datum(25), shares: datum(1_500_000), ownership_pct: datum(null), note: null }],
    movements: [{ issuer: 'Apple Inc', date: '2026-06-30', action: 'reduccion', shares: datum(-100_000), shares_after: datum(1_500_000), price_usd: datum(null), note: null }],
} as unknown as InvestorPortfolio;

describe('Ficha del inversor en inglés', () => {
    it('la cartera sale en inglés, con cifras en formato inglés', async () => {
        mocks.locale = 'en';
        withLocale(await Portfolio({ portfolio, view: 'posiciones' }));
        expect(screen.getByRole('region', { name: 'Declared portfolio' })).toBeTruthy();
        expect(screen.getByText(/^1 documented position · Jun 30, 2026$/)).toBeTruthy();
        expect(screen.getByText('Partial data')).toBeTruthy();
        expect(screen.getByText('Portfolio weight')).toBeTruthy();
        expect(screen.getByText('Stake in issuer')).toBeTruthy();
        expect(screen.getByText('1,500,000')).toBeTruthy();
        expect(screen.getByText('N/A')).toBeTruthy();
    });

    it('los últimos movimientos salen en inglés; en español no cambian', async () => {
        mocks.locale = 'en';
        const en = withLocale(await Portfolio({ portfolio, view: 'cambios' }));
        expect(screen.getByText('Reduced · Jun 30, 2026')).toBeTruthy();
        expect(screen.getByText('Shares · change')).toBeTruthy();
        expect(screen.getByText('Shares after')).toBeTruthy();
        en.unmount();
        mocks.locale = 'es';
        withLocale(await Portfolio({ portfolio, view: 'cambios' }));
        expect(screen.getByText(/^Reducción · /)).toBeTruthy();
        expect(screen.getByText('Acciones después')).toBeTruthy();
    });

    it('la ficha pública y el selector de vistas salen en inglés', async () => {
        mocks.locale = 'en';
        const profile = {
            vehicle: { name: 'Fund', type: 'UCITS', regulator_id: 'CNMV 1', start_date: '2015-01-01' },
            facts: [{ label: 'AUM', value: '1', kind: 'prensa', as_of: '2026', source_url: 'https://x.test' }],
            holdings_note: 'x', letters: [], meetings: [{ title: 'AGM', url: 'https://x.test/agm' }], links: [], provenance_note: '',
        } as unknown as PublicProfile;
        withLocale(await PublicProfileSection({ profile }));
        expect(screen.getByText(/Since 2015-01-01/)).toBeTruthy();
        expect(screen.getByRole('heading', { name: 'Published figures' })).toBeTruthy();
        expect(screen.getByText(/^Press · 2026$/)).toBeTruthy();
        expect(screen.getByRole('heading', { name: 'Annual meetings' })).toBeTruthy();
        withLocale(<InvestorViewSelector slug="buffett" view="cambios" />);
        const select = screen.getByRole('combobox', { name: 'Investor content' });
        expect(Array.from(select.querySelectorAll('option')).map((option) => option.textContent)).toEqual(['Portfolio', 'Allocation', 'Latest changes', 'Letters', 'Videos']);
    });

    it('la nota de total incompleto sale en inglés; en español no cambia', async () => {
        const noted = { ...portfolio, note: 'Valor total incompleto: faltan importes declarados de algunas posiciones; no se calculan pesos con un subtotal.' } as unknown as InvestorPortfolio;
        mocks.locale = 'en';
        const en = withLocale(await Portfolio({ portfolio: noted, view: 'posiciones' }));
        expect(screen.getByText('Incomplete total value: declared amounts for some positions are missing; no weights are derived from a subtotal.')).toBeTruthy();
        en.unmount();
        mocks.locale = 'es';
        withLocale(await Portfolio({ portfolio: noted, view: 'posiciones' }));
        expect(screen.getByText(/Valor total incompleto: faltan importes declarados/)).toBeTruthy();
    });

    it('el peso se deriva del total cuando el backend no lo trae; sin total queda N/A', async () => {
        const noWeights = {
            ...portfolio,
            note: null,
            coverage: null,
            positions: [
                { ...portfolio.positions[0], weight_pct: datum(null) },
                { ...portfolio.positions[0], issuer: 'Coca-Cola Co', cusip: '2', value_usd: datum(null), weight_pct: datum(null) },
            ],
        } as unknown as InvestorPortfolio;
        mocks.locale = 'en';
        const en = withLocale(await Portfolio({ portfolio: noWeights, view: 'distribucion' }));
        expect(screen.getByText(/25\.0\s*%/)).toBeTruthy();
        expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);
        en.unmount();
        const noTotal = { ...noWeights, total_value_usd: datum(null) } as unknown as InvestorPortfolio;
        withLocale(await Portfolio({ portfolio: noTotal, view: 'posiciones' }));
        expect(screen.queryByText(/25\.0\s*%/)).toBeNull();
    });
});
