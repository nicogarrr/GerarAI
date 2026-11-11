import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import DcaWatchCard from '@/components/watchlist/DcaWatchCard';
import DcaHitRatesCard from '@/components/watchlist/DcaHitRatesCard';
import type { DcaHitRates, DcaWatchCardData } from '@/lib/dca/types';
import { createTranslator } from '@/lib/i18n/translate';
import { blendOver, contrastRatio } from './contrast-helpers';
import fixture from '../watchlist-dca-card.fixture.json';

/**
 * Misma familia que el «(provisional)» del badge DCA (3,37:1 en prod):
 * tinta elegida a contraste máximo degradada por opacity-80, o elegida con
 * un umbral YIQ que no es WCAG y mispicka blanco donde el negro da el doble.
 */

const data = fixture as unknown as DcaWatchCardData;

function opacityOf(el: Element): number {
    const m = el.className.match(/opacity-(\d+)/);
    return m ? Number(m[1]) / 100 : 1;
}

describe('DcaWatchCard chips de marco temporal: contraste AA', () => {
    it('la etiqueta corta mantiene 4,5:1 sobre el color de zona (fixture real INTC, 4X #B400FF)', () => {
        render(<DcaWatchCard data={data} ti={createTranslator('es')} locale="es" />);
        for (const tf of data.timeframes) {
            if (!tf.available || !tf.zone) continue;
            const chip = screen.getByTestId(`dca-tf-${tf.key}`);
            const chipStyle = (chip as HTMLElement).style;
            const ink = chipStyle.color || '#FFFFFF';
            const worst = [...chip.querySelectorAll('span')].reduce((acc, el) => {
                const eff = blendOver(ink, tf.zone!.color, opacityOf(el));
                const ratio = contrastRatio(eff, tf.zone!.color);
                return ratio < acc.ratio ? { ratio, eff, opacity: opacityOf(el) } : acc;
            }, { ratio: Infinity, eff: '', opacity: 1 });
            expect(
                worst.ratio,
                `chip ${tf.key}: tinta ${ink} opacidad ${worst.opacity} -> ${worst.eff} sobre ${tf.zone.color}`,
            ).toBeGreaterThanOrEqual(4.5);
        }
    });
});

function hitRates(color: string): DcaHitRates {
    return {
        symbol: 'TEST',
        available: true,
        reason: null,
        months_completed: 12,
        first_period: '2025-01',
        last_period: '2025-12',
        horizons: [1],
        params_version: 'v1',
        evaluated_at: null,
        disclaimer: 'Solo histórico.',
        rows: [
            {
                key: '2x',
                label: '2X',
                levels: [2],
                color,
                signal_months: 4,
                cells: [{ horizon_months: 1, months: 4, pct_higher: 0.75, avg_return: 0.1 }],
            },
        ],
    };
}

describe('DcaHitRatesCard badge de nivel: contraste AA', () => {
    it.each(['#00AA78', '#FF193C', '#B400FF'])('elige tinta WCAG sobre la zona %s', (color) => {
        const { container } = render(<DcaHitRatesCard data={hitRates(color)} />);
        const badge = container.querySelector('[role="rowheader"] span[style]') as HTMLElement;
        expect(badge).toBeTruthy();
        const ink = badge.style.color || '#FFFFFF';
        expect(
            contrastRatio(ink, color),
            `tinta ${ink} sobre ${color}`,
        ).toBeGreaterThanOrEqual(4.5);
    });

    it('sin color de fila, la tinta cubre el fondo de reserva #374151', () => {
        const { container } = render(<DcaHitRatesCard data={hitRates(null as unknown as string)} />);
        const badge = container.querySelector('[role="rowheader"] span[style]') as HTMLElement;
        const ink = badge.style.color || '#FFFFFF';
        expect(contrastRatio(ink, '#374151')).toBeGreaterThanOrEqual(4.5);
    });
});
