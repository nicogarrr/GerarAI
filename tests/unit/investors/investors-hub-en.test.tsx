import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ usePathname: () => '/inversores/cartas' }));
vi.mock('@/lib/actions/investors.actions', () => ({ syncInvestorPortfoliosNow: vi.fn().mockResolvedValue({ success: false }) }));

import { HubNav } from '@/app/(root)/inversores/_components/HubNav';
import { Pagination } from '@/app/(root)/inversores/_components/Pagination';
import { SyncPortfoliosButton } from '@/app/(root)/inversores/_components/SyncPortfoliosButton';
import { periodLabel, usd } from '@/app/(root)/inversores/_components/format';
import { LocaleProvider } from '@/lib/i18n/client';

const en = (ui: React.ReactNode) => render(<LocaleProvider locale="en">{ui}</LocaleProvider>);

describe('Inversores en inglés: hub, navegación, sincronizar y paginación', () => {
    it('la barra del hub sale en inglés y marca Aprender en las cartas', () => {
        en(<HubNav />);
        expect(screen.getByRole('navigation', { name: 'Investors sections' })).toBeTruthy();
        expect(screen.getByRole('link', { name: 'Investors' })).toBeTruthy();
        expect(screen.getByRole('link', { name: 'Learn' }).getAttribute('aria-current')).toBe('page');
        expect(screen.getByRole('link', { name: '13F' })).toBeTruthy();
    });

    it('la paginación sale en inglés', () => {
        en(<Pagination basePath="/inversores" page={2} total={3} />);
        expect(screen.getByRole('navigation', { name: 'Pagination' })).toBeTruthy();
        expect(screen.getByText('Page 2 of 3')).toBeTruthy();
        expect(screen.getByRole('link', { name: 'Previous' }).getAttribute('href')).toBe('/inversores');
        expect(screen.getByRole('link', { name: 'Next' }).getAttribute('href')).toBe('/inversores?pagina=3');
    });

    it('el botón de sincronizar sale en inglés, también su error', async () => {
        en(<SyncPortfoliosButton />);
        expect(await screen.findByText("Couldn't queue the sync. Try again.")).toBeTruthy();
        expect(screen.getByRole('button', { name: /Sync portfolios now/ })).toBeTruthy();
    });

    it('fecha del informe y valor 13F siguen el idioma; en español no cambian', () => {
        expect(periodLabel('2026-06-30', 'en')).toBe('Jun 30, 2026');
        expect(periodLabel('2026-06-30')).toMatch(/30 jun 2026/);
        expect(periodLabel(null, 'en')).toBe('N/A');
        expect(periodLabel(null)).toBe('N/D');
        expect(usd(null, '2026-06-30', 'en')).toBe('N/A');
    });
});
