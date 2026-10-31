import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import DcaLevelBadge from '@/components/watchlist/DcaLevelBadge';
import type { DcaSignalItem } from '@/lib/dca/types';

function formingItem(): DcaSignalItem {
    return {
        symbol: 'GOOGL',
        company_name: 'Alphabet',
        sources: ['watchlist'],
        in_watchlist: true,
        in_portfolio: false,
        min_level_override: null,
        effective_min_level: 1,
        alerts_on: true,
        state: {
            key: '1x',
            label: '1X DCA',
            zone: 'Zona de compra',
            color: '#FFFFFF',
            fg: '#111111',
            level: 1,
            previous_level: 0,
            status: 'forming',
            period: '2026-10',
            signal_date: '2026-10-30',
            close: 280,
            currency: 'USD',
            currency_label: 'USD',
            metrics: {},
            level_prices: {},
            params_version: 'v1',
            data_source: 'yahoo',
            evaluated_at: '2026-10-30T22:00:00Z',
            last_alerted_level: 0,
            last_alerted_period: null,
        },
    };
}

describe('DcaLevelBadge en formación', () => {
    it('marca el nivel como provisional en vez de un separador colgante', () => {
        // Antes: «1X DCA ·» (punto suelto sin texto tras él, captura de prod).
        const { container } = render(<DcaLevelBadge item={formingItem()} signalMonths={null} />);
        const badge = screen.getByRole('button');
        expect(badge).toHaveTextContent('1X DCA');
        expect(badge).toHaveTextContent('(provisional)');
        expect(badge.textContent?.trim().endsWith('·')).toBe(false);
        expect(container.textContent?.includes('·')).toBe(false);
    });
});
