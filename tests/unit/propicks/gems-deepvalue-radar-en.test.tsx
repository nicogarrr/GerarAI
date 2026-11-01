import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const { getGems, reviewGems, getDeepValue, getRadarCandidates } = vi.hoisted(() => ({
    getGems: vi.fn(), reviewGems: vi.fn(), getDeepValue: vi.fn(), getRadarCandidates: vi.fn(),
}));
vi.mock('@/lib/actions/propicks-gems.actions', () => ({ getGems, reviewGems }));
vi.mock('@/lib/actions/propicks-deep-value.actions', () => ({ getDeepValue }));
vi.mock('@/lib/actions/propicks-radar.actions', () => ({ getRadarCandidates }));

import GemsView from '@/components/proPicks/GemsView';
import DeepValueView from '@/components/proPicks/DeepValueView';
import RadarGlobalView from '@/components/proPicks/RadarGlobalView';
import { gemReasonLabel, gemReasonValue } from '@/components/proPicks/gemsFormat';
import { LocaleProvider } from '@/lib/i18n/client';

const en = (ui: React.ReactNode) => render(<LocaleProvider locale="en">{ui}</LocaleProvider>);

describe('Pro Picks en inglés: joyas, deep value y radar global', () => {
    it('las joyas salen en inglés', async () => {
        getGems.mockResolvedValue([{
            ticker: 'ABC', name: 'Abc Corp', market_cap: 1_500_000_000, score: 73.25, review_status: 'reviewed', decision: 'keep',
            confidence: 0.8, thesis: null, risks: [], invalidation: 'margin drop',
            reasons: [{ key: 'managers_adding_13f', value: 7, source: '13F' }, { key: 'fcf_yield', value: 0.064, source: 'FMP' }],
        }]);
        en(<GemsView />);
        await waitFor(() => expect(screen.getByText('ABC')).toBeTruthy());
        expect(screen.getByText('Hidden gems')).toBeTruthy();
        expect(screen.getByText('Score')).toBeTruthy();
        expect(screen.getByText('73.3')).toBeTruthy();
        expect(screen.getByText('13F managers buying')).toBeTruthy();
        expect(screen.getByText('7 managers')).toBeTruthy();
        expect(screen.getByText('Kept by the AI')).toBeTruthy();
        expect(screen.getByText('What would invalidate it: margin drop')).toBeTruthy();
        expect(screen.getByRole('button', { name: /Review with AI/ })).toBeTruthy();
        expect(document.body.textContent).not.toMatch(/Puntuación|Actualizar|gestores/);
    });

    it('sin joyas, el estado vacío sale en inglés', async () => {
        getGems.mockResolvedValue([]);
        en(<GemsView />);
        await waitFor(() => expect(screen.getByText('No gems with the current data')).toBeTruthy());
    });

    it('deep value sale en inglés con filtros y cifras en formato inglés', async () => {
        getDeepValue.mockResolvedValue({ rotulo: null, resultados: [{
            ticker: 'XYZ', name: 'Xyz', score: 1234, sector: 'Banks', exchange: 'NYSE', price_to_book: 0.8456, pb_fiscal_year: 2025,
            pb_price_date: '2026-10-30', dividend_yield: null, metric_as_of: '2026-10-30', desacuerdo_fuentes: false, yield_extremo_revisar: false,
        }] });
        en(<DeepValueView />);
        await waitFor(() => expect(screen.getByText('XYZ')).toBeTruthy());
        expect(screen.getByRole('button', { name: 'P/B ≤ 1.0' })).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Any dividend' })).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Dividend ≥ 5%' })).toBeTruthy();
        expect(screen.getByText('0.85x')).toBeTruthy();
        expect(screen.getByText('1,234 pts')).toBeTruthy();
        expect(screen.getByText('P/B (book FY2025)')).toBeTruthy();
        expect(screen.getByText('Data as of October 30, 2026')).toBeTruthy();
        expect(screen.getByText(/^Deep value strategy:/)).toBeTruthy();
        expect(document.body.textContent).not.toMatch(/Dividendo|ptos|Datos al/);
    });

    it('el radar global sale en inglés', async () => {
        getRadarCandidates.mockResolvedValue({ generado_en: '2026-10-30T10:00:00Z', regiones: [], candidatos: [] });
        en(<RadarGlobalView />);
        expect(screen.getByRole('button', { name: 'Europe' })).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: /Find candidates/ }));
        await waitFor(() => expect(screen.getByText('The query returned no candidates with these filters.')).toBeTruthy());
        expect(document.body.textContent).toContain('Regions: global');
    });

    it('los motivos de las joyas, en inglés y en español igual', () => {
        expect(gemReasonLabel('net_debt_to_ebitda', 'en')).toBe('Net debt / EBITDA');
        expect(gemReasonLabel('net_debt_to_ebitda')).toBe('Deuda neta / EBITDA');
        expect(gemReasonValue({ key: 'managers_adding_13f', value: 1, source: 'x' } as never)).toBe('1 gestor');
    });
});
