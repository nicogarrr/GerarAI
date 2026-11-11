import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import DcaLevelBadge from '@/components/watchlist/DcaLevelBadge';
import { blendOver, contrastRatio } from './contrast-helpers';
import type { DcaSignalItem } from '@/lib/dca/types';

/**
 * Regresión de contraste WCAG AA: el «(provisional)» del badge DCA llevaba
 * `opacity-80`, que sobre el morado de la zona 4X (#b400ff) deja la tinta en
 * #f0ccff -> 3,37:1 (axe en prod, watchlist, 11 nov 2026). AA pide 4,5:1 para
 * texto de 11 px. El matiz «provisional» ya lo dan los paréntesis y el
 * font-normal; la opacidad no puede bajar la tinta por debajo de AA.
 */

function formingItem(color: string): DcaSignalItem {
    return {
        symbol: 'POOL',
        company_name: 'Pool Corp',
        sources: ['watchlist'],
        in_watchlist: true,
        in_portfolio: false,
        min_level_override: null,
        effective_min_level: 4,
        alerts_on: true,
        state: {
            key: '4x',
            label: '4X DCA',
            zone: 'Zona de compra fuerte',
            color,
            fg: '#FFFFFF',
            level: 4,
            previous_level: 3,
            status: 'forming',
            period: '2026-11',
            signal_date: '2026-11-10',
            close: 300,
            currency: 'USD',
            currency_label: 'USD',
            metrics: {},
            level_prices: {},
            params_version: 'v1',
            data_source: 'yahoo',
            evaluated_at: '2026-11-10T22:00:00Z',
            last_alerted_level: 0,
            last_alerted_period: null,
        },
    };
}

describe('DcaLevelBadge «(provisional)» contraste AA', () => {
    it.each(['#b400ff', '#00AA78', '#FF193C'])('mantiene 4,5:1 sobre la zona %s con cualquier opacidad aplicada', (color) => {
        render(<DcaLevelBadge item={formingItem(color)} signalMonths={null} />);
        const provisional = screen.getByText('(provisional)');
        const badge = screen.getByRole('button');
        const ink = badge.style.color || '#FFFFFF';
        const opacityMatch = provisional.className.match(/opacity-(\d+)/);
        const opacity = opacityMatch ? Number(opacityMatch[1]) / 100 : 1;
        const effective = blendOver(ink, color, opacity);
        expect(
            contrastRatio(effective, color),
            `tinta ${ink} con opacidad ${opacity} -> ${effective} sobre ${color}`,
        ).toBeGreaterThanOrEqual(4.5);
    });
});
