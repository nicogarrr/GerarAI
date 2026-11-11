import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getDcaBacktest } = vi.hoisted(() => ({ getDcaBacktest: vi.fn() }));
vi.mock('@/lib/actions/dca-signals.actions', () => ({ getDcaBacktest }));
vi.mock('@/components/watchlist/DcaHitRatesCard', () => ({ default: () => null }));

import DcaLevelBadge from '@/components/watchlist/DcaLevelBadge';
import DcaBacktestPanel from '@/components/proPicks/DcaBacktestPanel';
import { dcaCurrencyUnit, dcaPrice } from '@/lib/dca/format';
import type { DcaSignalItem } from '@/lib/dca/types';

// r5-front3: las vistas DCA fuera de la tarjeta (badge de la watchlist, backtest)
// pintaban el código del backend («70,00 USD») mientras el resto de la app,
// la tarjeta DCA incluida (#5388), dice «US$». Un único helper para todas.

const nbsp = (s: string | null) => (s ?? '').replace(/\u00a0/g, ' ');

describe('dcaPrice: formato de importe de la app con la divisa de la respuesta', () => {
    it('código ISO → «US$», «€»; peniques → «p»; nunca el código crudo', () => {
        expect(nbsp(dcaPrice(413.96, { currency: 'USD', currency_label: 'USD' }))).toBe('413,96 US$');
        expect(nbsp(dcaPrice(12.4, { currency: 'EUR', currency_label: 'EUR' }))).toBe('12,40 €');
        expect(nbsp(dcaPrice(118.25, { currency: 'GBp', currency_label: 'GBX (peniques)' }))).toBe('118,25 p');
        expect(nbsp(dcaPrice(1234.5, { currency: 'USD' }, 'en'))).toBe('$1,234.50');
    });
    it('sin código válido usa la etiqueta del backend, nunca una divisa prestada', () => {
        expect(nbsp(dcaPrice(5, { currency: null, currency_label: 'XYZ raro' }))).toBe('5,00 XYZ raro');
        expect(nbsp(dcaPrice(5, { currency: null, currency_label: null }))).toBe('5,00');
        expect(dcaPrice(null, { currency: 'USD' })).toBeNull();
    });
    it('unidad de «Precios en …»', () => {
        expect(dcaCurrencyUnit({ currency: 'USD', currency_label: 'USD' })).toBe('US$');
        expect(dcaCurrencyUnit({ currency: 'GBp', currency_label: 'GBX (peniques)' })).toBe('p');
        expect(dcaCurrencyUnit({ currency: null, currency_label: 'GBX (peniques)' })).toBe('GBX (peniques)');
    });
});

const item: DcaSignalItem = {
    symbol: 'UBER', company_name: 'Uber', sources: ['watchlist'], in_watchlist: true, in_portfolio: false,
    min_level_override: null, effective_min_level: 2, alerts_on: true,
    state: {
        key: '2x', label: '2X DCA', zone: 'Zona de compra', color: '#68F60F', fg: '#000000', level: 2, previous_level: 1,
        status: 'confirmed', period: '2026-09', signal_date: '2026-09-30', close: 70, currency: 'USD', currency_label: 'USD',
        metrics: {}, level_prices: { '3x': 60, '4x': 50 }, params_version: 'v1', data_source: 'yahoo',
        evaluated_at: '2026-10-27T22:00:00Z', last_alerted_level: 2, last_alerted_period: '2026-09',
    },
} as DcaSignalItem;

describe('DcaLevelBadge (watchlist): precios en «US$»', () => {
    it('cierre y precios de activación con el formato de la app', async () => {
        render(<DcaLevelBadge item={item} signalMonths={30} compact />);
        const badge = screen.getByRole('button', { name: /UBER: 2X DCA/ });
        fireEvent.pointerDown(badge, { pointerType: 'touch' });
        fireEvent.click(badge);
        await screen.findAllByText(/Cierre que activaría/);
        const text = nbsp(document.body.textContent);
        expect(text).toContain('60,00 US$');
        expect(text).toContain('50,00 US$');
        expect(text).not.toMatch(/\d USD/);
    });
});

const plan = (key: string, label: string) => ({
    key, label, invested: 12000, final_value: 15432.1, irr: 0.081, avg_cost: 45.5, max_drawdown: -0.25,
    worst_unrealized: -0.12, cash_left: 0, irr_vs_plain: 0.012, shares_per_money_vs_plain: 0.034, value_vs_plain: -0.02,
});
const data = {
    available: true, symbol: 'UBER', first_signal: '2016-01', last_signal: '2026-09', months: 129,
    valued_at_period: '2026-09', valued_at_date: '2026-09-30', valued_month_complete: true,
    currency: 'USD', currency_label: 'USD', params_version: 'v1',
    plans: [plan('plain', 'Plain'), plan('levels', 'Levels'), plan('fixed_budget', 'Fixed')],
    levels: [{ level: 1, label: '1X', months: 80, color: '#000' }], hit_rates: null, disclaimer: 'x',
};

describe('Backtest DCA: importes en «US$»', () => {
    beforeEach(() => getDcaBacktest.mockReset().mockResolvedValue({ data, error: null }));
    it('tabla y «Precios en» con el formato de la app', async () => {
        render(<DcaBacktestPanel />);
        fireEvent.submit(screen.getByRole('button', { name: /^Ejecutar$/ }).closest('form')!);
        await waitFor(() => expect(screen.getByText('Dinero aportado')).toBeTruthy());
        const text = nbsp(document.body.textContent);
        expect(text).toContain('12.000,00 US$');
        expect(text).toContain('15.432,10 US$');
        expect(text).not.toMatch(/\d USD/);
        expect(text).not.toMatch(/en USD/);
    });
});
