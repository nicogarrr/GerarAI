import { render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
const { getDeepValue } = vi.hoisted(() => ({ getDeepValue: vi.fn() }));
vi.mock('@/lib/actions/propicks-deep-value.actions', () => ({ getDeepValue }));
import DeepValueView from '@/components/proPicks/DeepValueView';
import { LocaleProvider } from '@/lib/i18n/client';

const base = { sector: 'Industrials', exchange: 'NYSE', price_to_book: 0.7, dividend_yield: 0.12,
    pb_price_date: '2026-11-13', pb_fiscal_year: 2025, metric_as_of: '2026-11-15',
    yield_extremo_revisar: false, desacuerdo_fuentes: false, finnhub_yield_indicated: null };
const good = { ...base, ticker: 'HIGH12', name: 'High dividend fixture', score: 58 };
const para = { ...base, ticker: 'PARA', name: 'Banzai International Inc', dividend_yield: 96.154,
    price_to_book: 0.00024422, score: null, desacuerdo_fuentes: true, yield_extremo_revisar: true,
    finnhub_yield_indicated: 0.0140746, review_reasons: ['yield_sources_disagree','yield_extreme','pb_split_basis_unverified'] };
const elme = { ...para, ticker: 'ELME', name: 'Elme Communities', dividend_yield: 34.8, price_to_book: 0.00406361 };

describe('Deep value: questionable data never becomes an opportunity score', () => {
    it.each(['es', 'en'] as const)('separates pending rows and preserves their raw numbers in %s', async (locale) => {
        getDeepValue.mockResolvedValue({ resultados: [good], pendientes_revision: [elme, para] });
        render(<LocaleProvider locale={locale}><DeepValueView /></LocaleProvider>);
        await waitFor(() => expect(screen.getByText('HIGH12')).toBeTruthy());
        const ranked = screen.getByTestId('deep-value-ranked');
        const pending = screen.getByTestId('deep-value-review');
        expect(within(ranked).queryByText('PARA')).toBeNull();
        expect(within(pending).getByText('PARA')).toBeTruthy();
        expect(within(pending).getByText('ELME')).toBeTruthy();
        expect(pending.textContent).not.toMatch(/ptos|pts/);
        expect(pending.textContent).toContain(locale === 'es' ? 'Pendiente de revisión de datos' : 'Pending data review');
        expect(pending.textContent).toContain(locale === 'es' ? 'base de acciones' : 'share basis');
        expect(pending.textContent).not.toContain('0,00x');
        expect(pending.textContent).not.toContain('0.00x');
        expect(pending.textContent).toContain(locale === 'es' ? '<0,01x' : '<0.01x');
    });
    it('fails closed against the old backend payload during a rolling deploy', async () => {
        getDeepValue.mockResolvedValue({ resultados: [{ ...para, score: 99.99 }, good] });
        render(<LocaleProvider locale="es"><DeepValueView /></LocaleProvider>);
        await waitFor(() => expect(screen.getByText('PARA')).toBeTruthy());
        expect(within(screen.getByTestId('deep-value-ranked')).queryByText('PARA')).toBeNull();
        expect(screen.queryByText(/99,99 ptos/)).toBeNull();
    });
    it('keeps pending rows visible when no candidate can be ranked', async () => {
        getDeepValue.mockResolvedValue({ resultados: [], pendientes_revision: [para] });
        render(<LocaleProvider locale="es"><DeepValueView /></LocaleProvider>);
        await waitFor(() => expect(screen.getByText('PARA')).toBeTruthy());
        expect(screen.getByText('No hay candidatos con datos aptos para puntuar.')).toBeTruthy();
    });
    it('keeps an honest empty state for a genuinely empty screen', async () => {
        getDeepValue.mockResolvedValue({ resultados: [], pendientes_revision: [] });
        render(<LocaleProvider locale="en"><DeepValueView /></LocaleProvider>);
        await waitFor(() => expect(screen.getByText("No company in the universe passes these filters with recent data. Valuation metrics are computed every night after the close; if they were just deployed, the first run hasn't arrived yet.")).toBeTruthy());
        expect(screen.queryByTestId('deep-value-review')).toBeNull();
    });
});
