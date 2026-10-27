import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import DcaLevelBadge from '@/components/watchlist/DcaLevelBadge';
import { dcaDataAge } from '@/lib/dca/format';
import type { DcaSignalItem, DcaSignalState } from '@/lib/dca/types';

function item(extra: Partial<DcaSignalState> = {}): DcaSignalItem {
    return {
        symbol: 'UBER',
        company_name: 'Uber',
        sources: ['watchlist'],
        in_watchlist: true,
        in_portfolio: false,
        min_level_override: null,
        effective_min_level: 2,
        alerts_on: true,
        state: {
            key: '3x',
            label: '3X DCA',
            zone: 'Zona de compra fuerte',
            color: '#68F60F',
            fg: '#000000',
            level: 3,
            previous_level: 2,
            status: 'confirmed',
            period: '2026-10',
            signal_date: '2026-10-16',
            close: 70,
            currency: 'USD',
            currency_label: 'USD',
            metrics: {},
            level_prices: {},
            params_version: 'v1',
            data_source: 'yahoo',
            evaluated_at: '2026-10-27T22:00:00Z',
            last_alerted_level: 3,
            last_alerted_period: '2026-10',
            ...extra,
        },
    };
}

describe('dcaDataAge', () => {
    it('formatea la edad en días', () => {
        expect(dcaDataAge(0)).toBe('hoy');
        expect(dcaDataAge(1)).toBe('hace 1 día');
        expect(dcaDataAge(9)).toBe('hace 9 días');
        expect(dcaDataAge(null)).toBeNull();
        expect(dcaDataAge(undefined)).toBeNull();
        expect(dcaDataAge(-1)).toBeNull();
    });
});

describe('DcaLevelBadge desactualizado', () => {
    it('nivel con datos viejos: muestra «desactualizado» y la edad', () => {
        render(<DcaLevelBadge item={item({ stale: true, data_age_days: 9 })} signalMonths={30} compact />);
        expect(screen.getByTestId('dca-stale')).toHaveTextContent('desactualizado · hace 9 días');
        expect(screen.getByRole('button')).toHaveAccessibleName(/3X DCA.*desactualizado · hace 9 días/);
    });

    it('stale sin edad conocida: solo «desactualizado»', () => {
        render(<DcaLevelBadge item={item({ stale: true, data_age_days: null })} signalMonths={30} />);
        expect(screen.getByTestId('dca-stale')).toHaveTextContent(/^desactualizado$/);
    });

    it('datos al día o backend antiguo sin el campo: sin aviso', () => {
        const { rerender } = render(<DcaLevelBadge item={item({ stale: false, data_age_days: 2 })} signalMonths={30} />);
        expect(screen.queryByTestId('dca-stale')).not.toBeInTheDocument();
        expect(screen.getByRole('button')).toHaveTextContent('3X DCA');
        rerender(<DcaLevelBadge item={item()} signalMonths={30} />);
        expect(screen.queryByTestId('dca-stale')).not.toBeInTheDocument();
    });
});
