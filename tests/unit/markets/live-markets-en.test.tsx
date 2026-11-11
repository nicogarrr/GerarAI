import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/live-quotes.actions', () => ({ getLiveMarkets: async () => null }));

import { LiveMarketsPanel } from '@/components/markets/LiveMarketsPanel';
import { LocaleProvider } from '@/lib/i18n/client';
import { formatQuoteAge, formatQuoteChangePercent, localizeInstrumentType, type LiveMarketsResult } from '@/lib/market/live-quotes';

const PANEL_DATA: LiveMarketsResult = {
    fetchedAt: 1_762_000_000_000,
    groups: [
        {
            key: 'indice',
            quotes: [
                {
                    symbol: '^GSPC',
                    name: 'S&P 500',
                    kind: 'indice',
                    unit: 'index',
                    decimals: 2,
                    price: 6000.12,
                    change: 10.5,
                    changePercent: 0.18,
                    timestamp: 1_762_000_000,
                    currency: 'USD',
                    session: 'regular',
                    exchangeName: null,
                    instrumentType: null,
                },
            ],
        },
    ],
};

describe('Mercados en directo en inglés', () => {
    it('panel en inglés', () => {
        render(<LocaleProvider locale="en"><LiveMarketsPanel initial={null} /></LocaleProvider>);
        expect(screen.getAllByText('Quote provider unavailable. Retrying every minute.')[0]).toBeTruthy();
        expect(screen.getByRole('tab', { name: 'Commodities' })).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Refresh now' })).toBeTruthy();
    });

    it('en español no cambia', () => {
        render(<LocaleProvider locale="es"><LiveMarketsPanel initial={null} /></LocaleProvider>);
        expect(screen.getAllByText('Proveedor de cotizaciones no disponible. Se reintenta cada minuto.')[0]).toBeTruthy();
        expect(screen.getByRole('tab', { name: 'Materias primas' })).toBeTruthy();
    });

    it('la tabla tiene nombre y cabeceras de columna accesibles', () => {
        render(<LocaleProvider locale="en"><LiveMarketsPanel initial={PANEL_DATA} /></LocaleProvider>);
        expect(screen.getByRole('table', { name: 'Live quotes: Indices' })).toBeTruthy();
        expect(screen.getByRole('columnheader', { name: 'Instrument' })).toBeTruthy();
        expect(screen.getByRole('columnheader', { name: 'Price' })).toBeTruthy();
        expect(screen.getByRole('columnheader', { name: 'Change' })).toBeTruthy();
    });

    it('cabeceras accesibles en español', () => {
        render(<LocaleProvider locale="es"><LiveMarketsPanel initial={PANEL_DATA} /></LocaleProvider>);
        expect(screen.getByRole('table', { name: 'Cotizaciones en directo: Índices' })).toBeTruthy();
        expect(screen.getByRole('columnheader', { name: 'Instrumento' })).toBeTruthy();
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
