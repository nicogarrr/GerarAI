import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/live-quotes.actions', () => ({ getLiveMarkets: async () => null }));

import { LiveMarketsPanel } from '@/components/markets/LiveMarketsPanel';
import { LocaleProvider } from '@/lib/i18n/client';
import { formatQuoteAge, formatQuoteChangePercent, localizeInstrumentType } from '@/lib/market/live-quotes';

describe('Mercados en directo en inglés', () => {
    it('panel en inglés', () => {
        render(<LocaleProvider locale="en"><LiveMarketsPanel initial={null} /></LocaleProvider>);
        expect(screen.getByText('No data yet')).toBeTruthy();
        expect(screen.getByRole('tab', { name: 'Commodities' })).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Refresh now' })).toBeTruthy();
    });

    it('en español no cambia', () => {
        render(<LocaleProvider locale="es"><LiveMarketsPanel initial={null} /></LocaleProvider>);
        expect(screen.getByText('Sin datos todavía')).toBeTruthy();
        expect(screen.getByRole('tab', { name: 'Materias primas' })).toBeTruthy();
    });

    it('edad, cambio y tipo según idioma', () => {
        expect(formatQuoteAge(125)).toBe('hace ~2 min');
        expect(formatQuoteAge(125, 'en')).toBe('~2 min ago');
        expect(formatQuoteAge(3900, 'en')).toBe('1 h 5 min ago');
        expect(formatQuoteChangePercent(1.5, 'en')).toBe('+1.50');
        expect(formatQuoteChangePercent(1.5)).toBe('+1,50');
        expect(localizeInstrumentType('EQUITY', 'en')).toBe('stock');
        expect(localizeInstrumentType('EQUITY')).toBe('acción');
    });
});
