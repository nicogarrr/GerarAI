import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import DcaLevelBadge from '@/components/watchlist/DcaLevelBadge';
import type { DcaSignalItem } from '@/lib/dca/types';

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

describe('DcaLevelBadge en móvil', () => {
    it('un toque abre el detalle (zona y cierres que activarían 3X/4X), no solo el hover', async () => {
        render(<DcaLevelBadge item={item} signalMonths={30} compact />);
        const badge = screen.getByRole('button', { name: /UBER: 2X DCA/ });
        fireEvent.pointerDown(badge, { pointerType: 'touch' });
        fireEvent.click(badge);
        expect((await screen.findAllByText(/Cierre que activaría/)).length).toBeGreaterThan(0);
        expect(badge).toHaveAttribute('aria-expanded', 'true');
        // Segundo toque: se cierra.
        fireEvent.pointerDown(badge, { pointerType: 'touch' });
        fireEvent.click(badge);
        expect(badge).toHaveAttribute('aria-expanded', 'false');
    });
});
