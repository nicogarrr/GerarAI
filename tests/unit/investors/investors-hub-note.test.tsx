import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
    locale: 'en',
    investors: [] as Record<string, unknown>[],
    offline: false as false | 'app' | 'other',
}));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: mocks.locale }) }) }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => '/inversores' }));
vi.mock('@/lib/actions/investors.actions', () => ({
    getInvestors: async () => {
        if (mocks.offline === 'app') {
            const { AppError } = await import('@/lib/types/errors');
            throw new AppError('down', 'EXTERNAL_API_ERROR');
        }
        if (mocks.offline === 'other') throw new Error('boom');
        return { investors: mocks.investors };
    },
    syncInvestorPortfoliosNow: vi.fn().mockResolvedValue({ success: false }),
}));
vi.mock('@/app/(root)/inversores/_components/Avatar', () => ({
    InvestorAvatar: ({ name }: { name: string }) => <span>{name}</span>,
}));

import InvestorsPage, { generateMetadata } from '@/app/(root)/inversores/page';
import { LocaleProvider } from '@/lib/i18n/client';

const INCOMPLETE_TOTAL_ES = 'Valor total incompleto: faltan importes declarados de algunas posiciones; no se calculan pesos con un subtotal.';
const INCOMPLETE_TOTAL_EN = 'Incomplete total value: declared amounts for some positions are missing; no weights are derived from a subtotal.';

const investor = (note: string | null) => ({
    slug: 'buffett',
    name: 'Warren Buffett',
    firm: 'Berkshire Hathaway',
    official_name: null,
    has_13f: true,
    report_date: '2026-06-30',
    positions: 1,
    value_usd_thousands: null,
    coverage: null,
    note,
});

const renderPage = async () => render(<LocaleProvider locale={mocks.locale as 'es' | 'en'}>
    {await InvestorsPage({ searchParams: Promise.resolve({}) })}
</LocaleProvider>);

describe('Hub de inversores: nota de calidad del total', () => {
    it('la nota de total incompleto sale en inglés; en español no cambia', async () => {
        mocks.investors = [investor(INCOMPLETE_TOTAL_ES)];
        mocks.locale = 'en';
        const en = await renderPage();
        expect(screen.getByText(INCOMPLETE_TOTAL_EN)).toBeTruthy();
        en.unmount();
        mocks.locale = 'es';
        await renderPage();
        expect(screen.getByText(INCOMPLETE_TOTAL_ES)).toBeTruthy();
    });

    it('sin nota no se pinta nada extra', async () => {
        mocks.investors = [investor(null)];
        mocks.locale = 'en';
        await renderPage();
        expect(screen.queryByText(/Incomplete total value/)).toBeNull();
        expect(screen.getByRole('link', { name: /Warren Buffett/ })).toBeTruthy();
    });

    it('con el backend caído sale la pantalla de reintento', async () => {
        mocks.offline = 'app';
        mocks.locale = 'en';
        await renderPage();
        expect(screen.queryByRole('link', { name: /Warren Buffett/ })).toBeNull();
        mocks.offline = false;
    });

    it('el resto de tarjetas del hub se pintan según su estado', async () => {
        mocks.investors = [
            { ...investor(null), slug: 'a', name: 'Sin Sync', report_date: null, has_13f: true },
            { ...investor(null), slug: 'b', name: 'Perfil Publico', report_date: null, has_13f: false, has_public_profile: true },
            { ...investor(null), slug: 'c', name: 'Sin 13F', report_date: null, has_13f: false },
            { ...investor(null), slug: 'd', name: 'Parcial', coverage: 'partial', positions: null, note: 'Sin datos: no presenta 13F' },
        ];
        mocks.locale = 'en';
        await renderPage();
        expect(screen.getByRole('link', { name: /Sin Sync/ })).toBeTruthy();
        expect(screen.getByRole('link', { name: /Perfil Publico/ })).toBeTruthy();
        expect(screen.getByRole('link', { name: /Sin 13F/ })).toBeTruthy();
        const partial = screen.getByRole('link', { name: /Parcial/ });
        expect(partial.textContent).toContain('No data: no 13F on file.');
    });

    it('un error que no es de backend caído se propaga', async () => {
        mocks.offline = 'other';
        await expect(renderPage()).rejects.toThrow('boom');
        mocks.offline = false;
    });

    it('los metadatos salen en el idioma activo', async () => {
        mocks.locale = 'en';
        const metadata = await generateMetadata();
        expect(String(metadata.title)).toBeTruthy();
    });
});
