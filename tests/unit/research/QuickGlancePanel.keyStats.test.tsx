import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// Server component asíncrono (getT lee la cookie de locale).
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));

import { QuickGlancePanel } from '@/components/research/QuickGlancePanel';
import type { KeyStats } from '@/lib/research/key-stats';

type Props = Parameters<typeof QuickGlancePanel>[0];
const base: Props = {
    ticker: 'TEST',
    currency: 'USD',
    model: null,
    analysts: null,
    livePrice: null,
    shareCapital: null,
    credibility: null,
    moatScore: null,
};

const stats = (over: Partial<KeyStats> = {}): KeyStats => ({
    symbol: 'TEST',
    fetched_at: 0,
    currency: 'USD',
    range_52w: { low: 80, high: 130.5, source: 'Cierres diarios guardados en GerarAI', sessions: 250 },
    next_earnings: { date: '2026-11-12', upcoming: true, confirmed: false, source: 'Yahoo Finance (calendarEvents)' },
    ex_dividend: { date: '2026-11-05', upcoming: true, source: 'Yahoo Finance (no oficial)' },
    beta: { value: 1.234, source: 'Yahoo Finance (no oficial), beta a 5 años con datos mensuales' },
    ...over,
});

describe('QuickGlancePanel · datos clave (estilo Stock Analysis)', () => {
    it('pinta resultados, ex-dividendo, rango 52 semanas y beta con su fuente', async () => {
        render(await QuickGlancePanel({ ...base, keyStats: stats() }));
        expect(screen.getByText('Próximos resultados')).toBeVisible();
        expect(screen.getByText('12 nov 2026')).toBeVisible();
        expect(screen.getByText('Fecha estimada')).toBeVisible();
        expect(screen.getByText('Próximo ex-dividendo')).toBeVisible();
        expect(screen.getByText('5 nov 2026')).toBeVisible();
        expect(screen.getByText('Rango 52 semanas')).toBeVisible();
        expect(screen.getByText('80,00 US$ – 130,50 US$')).toBeVisible();
        expect(screen.getByText('Con los cierres diarios guardados')).toBeVisible();
        expect(screen.getByText('Beta')).toBeVisible();
        expect(screen.getByText('1,23')).toBeVisible();
        // Filas informativas: no enlazan a ninguna sección.
        expect(screen.queryByRole('link', { name: /Beta/ })).toBeNull();
    });

    it('un ex-dividendo pasado se rotula como el último, sin etiqueta de fuente (orden 31-oct)', async () => {
        render(await QuickGlancePanel({
            ...base,
            keyStats: stats({
                ex_dividend: { date: '2026-08-11', upcoming: false, source: 'Yahoo Finance (no oficial)' },
                range_52w: { low: 1, high: 2, source: 'Yahoo Finance (no oficial), rango intradía' },
                next_earnings: null,
                beta: null,
            }),
        }));
        expect(screen.getByText('Último ex-dividendo')).toBeVisible();
        expect(screen.queryByText(/Yahoo/i)).toBeNull();
        expect(screen.queryByText(/Fuente de mercado/i)).toBeNull();
        expect(screen.queryByText('Próximos resultados')).toBeNull();
        expect(screen.queryByText('Beta')).toBeNull();
    });

    it('sin datos clave no pinta filas de relleno', async () => {
        const out = await QuickGlancePanel({ ...base, keyStats: stats({ range_52w: null, next_earnings: null, ex_dividend: null, beta: null }) });
        expect(out).toBeNull();
    });
});
