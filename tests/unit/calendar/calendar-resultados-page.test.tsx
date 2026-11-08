// La página es un server component traducido con getT(): lib/i18n/server lee
// la cookie de locale vía next/headers; sin cookie el locale es «es».
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * /calendar/resultados: próximos vs recientes (7 días de historia, día de
 * Madrid), huecos declarados (sin fecha / fecha caducada son cosas distintas)
 * y estados vacíos que orientan. El material SEC se mockea: estos tests no
 * certifican el streaming del material ni su fallback.
 */
const getFollowedEarnings = vi.fn();
vi.mock('@/lib/actions/catalysts.actions', () => ({
    getFollowedEarnings: (...a: unknown[]) => getFollowedEarnings(...a),
}));
vi.mock('@/lib/actions/earnings-materials.actions', () => ({
    getEarningsMaterials: () => Promise.resolve({}),
}));
vi.mock('@/lib/backend-offline', () => ({ isBackendUnavailableError: () => true }));
vi.mock('@/components/system/BackendOffline', () => ({ default: () => <p>backend caído</p> }));

import FollowedEarningsPage from '@/app/(root)/calendar/resultados/page';
import type { FollowedEarningsEvent } from '@/lib/actions/catalysts.actions';

// 2026-11-08 12:00 UTC = 2026-11-08 en Madrid (CET, UTC+1).
const NOW = new Date('2026-11-08T12:00:00Z');

const ev = (over: Partial<FollowedEarningsEvent> = {}): FollowedEarningsEvent => ({
    ticker: 'KO', company: 'Coca-Cola', origin: 'cartera', date: '2026-11-10', session: 'pre_market',
    fiscal_label: 'Sep/2026', confirmed: true, source: 'Nasdaq', source_url: 'https://example.com/ko', ...over,
});

const calendarWith = (days: { date: string; events: FollowedEarningsEvent[] }[], over: object = {}) => ({
    desde: '2026-11-01', hasta: '2027-01-07', followed_count: 2, count: days.length,
    days, without_date_in_range: [], ...over,
});

beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    getFollowedEarnings.mockReset();
});
afterEach(() => vi.useRealTimers());

describe('página de resultados seguidos', () => {
    it('consulta desde hace 7 días hasta +60, con el día de Madrid', async () => {
        getFollowedEarnings.mockResolvedValue(calendarWith([]));
        render(await FollowedEarningsPage());
        expect(getFollowedEarnings).toHaveBeenCalledWith({ desde: '2026-11-01', hasta: '2027-01-07' });
    });

    it('separa próximos de recientes y los recientes van del más nuevo al más viejo', async () => {
        getFollowedEarnings.mockResolvedValue(
            calendarWith([
                { date: '2026-11-06', events: [ev({ ticker: 'OLD', company: 'Vieja SA', date: '2026-11-06' })] },
                { date: '2026-11-07', events: [ev({ ticker: 'NEW', company: 'Reciente SA', date: '2026-11-07' })] },
                { date: '2026-11-10', events: [ev()] },
            ]),
        );
        render(await FollowedEarningsPage());
        expect(screen.getByText(/Resultados recientes \(últimos 7 días\)/)).toBeInTheDocument();
        const reciente = screen.getByText('Reciente SA');
        const vieja = screen.getByText('Vieja SA');
        expect(reciente.compareDocumentPosition(vieja) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it('sin empresas seguidas y sin eventos: avisos distintos y accionables', async () => {
        getFollowedEarnings.mockResolvedValue(calendarWith([], { followed_count: 0 }));
        const { unmount } = render(await FollowedEarningsPage());
        expect(screen.getByText(/Aún no sigues ninguna empresa/)).toBeInTheDocument();
        unmount();
        getFollowedEarnings.mockResolvedValue(calendarWith([]));
        render(await FollowedEarningsPage());
        expect(screen.getByText(/No hay fechas de resultados vigentes/)).toBeInTheDocument();
    });

    it('sin fecha y fecha caducada no se mezclan: el ticker caducado sale solo en su aviso', async () => {
        getFollowedEarnings.mockResolvedValue(
            calendarWith([{ date: '2026-11-10', events: [ev()] }], {
                without_date_in_range: ['ASTS', 'ZETA'],
                stale_date_in_range: ['ZETA'],
            }),
        );
        render(await FollowedEarningsPage());
        expect(screen.getByText(/Sin fecha vigente en el calendario: ASTS/)).toBeInTheDocument();
        expect(screen.getByText(/Fecha pendiente de actualizar.*: ZETA/)).toBeInTheDocument();
    });

    it('backend caído: pantalla de reintento, no un error en crudo', async () => {
        getFollowedEarnings.mockRejectedValue(new Error('ECONNREFUSED'));
        render(await FollowedEarningsPage());
        expect(screen.getByText('backend caído')).toBeInTheDocument();
    });
});
