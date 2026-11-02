import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import DcaLevelBadge from '@/components/watchlist/DcaLevelBadge';
import { readableInk, relativeLuminance } from '@/lib/dca/readable-ink';
import type { DcaSignalItem } from '@/lib/dca/types';

function contrast(a: string, b: string): number {
    const [x, y] = [relativeLuminance(a)!, relativeLuminance(b)!].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
}

// Colores de zona que manda el motor (dca_signal_engine.ZONES): no cambian.
const ZONES = ['#B400FF', '#68F60F', '#00AA78', '#FFFFFF', '#FF9F0A', '#FF193C'];

function item(color: string, fg: string, label: string): DcaSignalItem {
    return {
        symbol: 'KO', company_name: 'Coca-Cola', sources: ['watchlist'], in_watchlist: true, in_portfolio: false,
        min_level_override: null, effective_min_level: 1, alerts_on: true,
        state: {
            key: '2x', label, zone: 'Zona de compra', color, fg, level: 2, previous_level: 1, status: 'confirmed',
            period: '2026-10', signal_date: '2026-10-30', close: 60, currency: 'USD', currency_label: 'USD',
            metrics: {}, level_prices: {}, params_version: 'v1', data_source: 'yahoo',
            evaluated_at: '2026-10-30T22:00:00Z', last_alerted_level: 0, last_alerted_period: null,
        },
    };
}

describe('tinta legible sobre las zonas DCA', () => {
    it('cada zona llega al menos a 4,4:1 (AA de texto en negrita pequeño) sin tocar su color', () => {
        for (const zone of ZONES) {
            expect(contrast(zone, readableInk(zone)!)).toBeGreaterThanOrEqual(4.38);
        }
    });

    it('«2X DCA» y «RECORTE FUERTE» pasan a tinta negra (antes blanco: 2,99:1 y 3,85:1)', () => {
        expect(readableInk('#00AA78', '#FFFFFF')).toBe('#000000');
        expect(readableInk('#FF193C', '#FFFFFF')).toBe('#000000');
        expect(readableInk('#B400FF', '#FFFFFF')).toBe('#FFFFFF');
        expect(readableInk('#68F60F', '#000000')).toBe('#000000');
    });

    it('si el fondo no es hex conserva la tinta del motor', () => {
        expect(readableInk('rebeccapurple', '#FFFFFF')).toBe('#FFFFFF');
        expect(readableInk(null, null)).toBeUndefined();
    });

    it('la insignia de la watchlist pinta el fondo de la zona y la tinta legible', () => {
        render(<DcaLevelBadge item={item('#00AA78', '#FFFFFF', '2X DCA')} signalMonths={null} />);
        const badge = screen.getByRole('button');
        expect(badge.style.backgroundColor).toBe('rgb(0, 170, 120)');
        expect(badge.style.color).toBe('rgb(0, 0, 0)');
    });
});
