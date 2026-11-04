import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// Server component asíncrono: el locale sale de la cookie gerarai_locale.
const cookie = vi.hoisted(() => ({ locale: 'en' as string | undefined }));
vi.mock('next/headers', () => ({
    cookies: async () => ({ get: (name: string) => (name === 'gerarai_locale' && cookie.locale ? { value: cookie.locale } : undefined) }),
}));

import { QuickGlancePanel } from '@/components/research/QuickGlancePanel';
import type { AnalystTargets } from '@/lib/research/analyst-targets';
import type { KeyStats } from '@/lib/research/key-stats';

type Props = Parameters<typeof QuickGlancePanel>[0];
const analysts = { status: 'available', currency: 'USD', consensus: { median: 630 } } as unknown as AnalystTargets;
const keyStats: KeyStats = {
    symbol: 'TEST',
    fetched_at: 0,
    currency: 'USD',
    range_52w: { low: 406.48, high: 512.78, source: 'Cierres diarios guardados en GerarAI', sessions: 250 },
    next_earnings: null,
    ex_dividend: { date: '2026-11-19', upcoming: true, source: 'Yahoo Finance (no oficial)' },
    beta: null,
} as unknown as KeyStats;
const props: Props = {
    ticker: 'TEST', currency: 'USD', model: null, analysts, livePrice: 336.56,
    shareCapital: null, credibility: null, moatScore: null, keyStats,
};

// E2E local (4-nov-2026, /research/MSFT en inglés): el vistazo rápido salía
// «Upside to median: +87,2 %», «Median 630,00 US$», «19 nov 2026» y
// «406,48 US$ – 512,78 US$»: textos en inglés con cifras y fechas en castellano.
describe('QuickGlancePanel: cifras y fechas con el idioma activo', () => {
    it('en inglés', async () => {
        cookie.locale = 'en';
        const { container } = render(await QuickGlancePanel(props));
        const text = container.textContent ?? '';
        expect(screen.getByText('Upside to median: +87.2%')).toBeVisible();
        expect(text).toContain('$630.00');
        expect(text).toContain('$406.48 – $512.78');
        expect(text).toMatch(/Nov 19, 2026|19 Nov 2026/);
        expect(text).not.toMatch(/US\$|87,2|630,00|nov 2026/);
    });

    it('en castellano sigue igual', async () => {
        cookie.locale = undefined;
        const { container } = render(await QuickGlancePanel(props));
        const text = container.textContent ?? '';
        expect(text).toMatch(/\+87,2\s?%/);
        expect(text).toMatch(/630,00\s?US\$/);
        expect(text).toContain('19 nov 2026');
    });
});
