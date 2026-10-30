import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/dca-signals.actions', () => ({ getDcaBacktest: vi.fn() }));

import { valuationLabel } from '@/components/proPicks/DcaBacktestPanel';

describe('backtest DCA: fecha de valoración honesta', () => {
    it('mes en curso: último cierre con su fecha, no «el cierre de» un mes sin cerrar', () => {
        const label = valuationLabel({ valued_at_period: '2026-10', valued_at_date: '2026-10-29', valued_month_complete: false });
        expect(label).toBe('valorado al último cierre disponible (29 oct 2026, mes en curso)');
    });
    it('mes cerrado (o backend antiguo sin el campo): el cierre del mes', () => {
        expect(valuationLabel({ valued_at_period: '2026-09', valued_at_date: '2026-09-30', valued_month_complete: true })).toBe('valorado al cierre de 2026-09');
        expect(valuationLabel({ valued_at_period: '2026-09' })).toBe('valorado al cierre de 2026-09');
    });
});
