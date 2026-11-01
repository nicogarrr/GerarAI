import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ProPick } from '@/lib/actions/proPicks.actions';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

import MonthlyRebalanceView from '@/components/proPicks/MonthlyRebalanceView';
import StrategySelector from '@/components/proPicks/StrategySelector';
import { STRATEGY_CATALOG, monthLabel, monthLabelEs, reasonDisplayText } from '@/components/proPicks/monthlyRebalance';
import { previousSnapshotError, previousSnapshotRejection } from '@/components/proPicks/snapshotValidation';
import { localizeStrategy } from '@/components/proPicks/strategy-display';
import { LocaleProvider } from '@/lib/i18n/client';
import { createTranslator } from '@/lib/i18n/translate';

const en = (ui: React.ReactNode) => render(<LocaleProvider locale="en">{ui}</LocaleProvider>);

const pick = (over: Record<string, unknown> = {}): ProPick =>
    ({
        symbol: 'AAPL', company: 'Apple', score: 75.4, grade: 'B+',
        categoryScores: { value: 60, growth: 70, profitability: 80, cashFlow: 65, momentum: 55, debtLiquidity: 50 },
        reasons: [], confidenceReasons: [], confidence: 72, confidenceLevel: 'Media', asOf: '2026-10-27',
        facts: { return12M: 12 }, ...over,
    }) as unknown as ProPick;

describe('Pro Picks en inglés: rebalanceo mensual y selector de estrategia', () => {
    it('el rebalanceo sin mes anterior sale en inglés, con el motivo traducido solo al pintarlo', () => {
        en(<MonthlyRebalanceView currentPicks={[pick()]} month="2026-09" />);
        expect(screen.getByText('September 2026 rebalancing')).toBeTruthy();
        expect(screen.getByText(/AI Adaptive Selection · 1 current stocks · without a previous-month comparison/)).toBeTruthy();
        expect(screen.getByText('Current selection · September 2026')).toBeTruthy();
        expect(screen.getByText(/doesn't keep a month-by-month history/)).toBeTruthy();
        expect(screen.getByText('Score 75/100 with medium confidence')).toBeTruthy();
        expect(screen.getByRole('button', { name: /Download JSON snapshot/ })).toBeTruthy();
        expect(screen.getByRole('button', { name: /Load previous snapshot/ })).toBeTruthy();
        expect(document.body.textContent).not.toMatch(/Rebalanceo|vigente|Descargar|confianza/);
    });

    it('cargando y con error, los estados salen en inglés', () => {
        const { unmount } = en(<MonthlyRebalanceView currentPicks={[]} picksStatus="loading" month="2026-09" />);
        expect(screen.getByText("Loading this strategy's picks…")).toBeTruthy();
        unmount();
        en(<MonthlyRebalanceView currentPicks={[]} picksStatus="error" month="2026-09" />);
        expect(screen.getByText("The strategy's picks are unavailable.")).toBeTruthy();
    });

    it('los motivos guardados en el snapshot siguen en español y se traducen al pintar', () => {
        expect(reasonDisplayText('Estaba en la selección del mes anterior', 'en')).toBe("It was in the previous month's selection");
        expect(reasonDisplayText('Estaba en la selección del mes anterior')).toBe('Estaba en la selección del mes anterior');
        expect(reasonDisplayText('Margen FCF 12 %', 'en')).toBe('Margen FCF 12 %');
        expect(monthLabel('2026-09', 'en')).toBe('September 2026');
        expect(monthLabelEs('2026-09').toLowerCase()).toContain('septiembre');
    });

    it('el motivo de rechazo del snapshot anterior tiene código y el texto español no cambia', () => {
        const snap = { kind: 'cavaai-propicks-monthly-snapshot', version: 1, month: '2026-08', strategyId: 'value', generatedAt: '', picks: [] } as const;
        expect(previousSnapshotRejection({ ...snap, picks: [] }, 'adaptive', '2026-09')).toBe('otherStrategy');
        expect(previousSnapshotRejection({ ...snap, picks: [], month: '2026-09' }, 'value', '2026-09')).toBe('notPrevious');
        expect(previousSnapshotRejection({ ...snap, picks: [] }, 'value', '2026-09')).toBeNull();
        expect(previousSnapshotError({ ...snap, picks: [] }, 'adaptive', '2026-09')).toMatch(/otra estrategia/);
    });

    it('el selector y los nombres de estrategia salen en inglés; en español no cambian', () => {
        const t = createTranslator('en');
        const catalog = STRATEGY_CATALOG.map((s) => localizeStrategy(s, 'en', t));
        expect(catalog.map((s) => s.name)).toEqual(['AI Adaptive Selection', 'Value', 'Momentum', 'Defensive']);
        expect(localizeStrategy(STRATEGY_CATALOG[3], 'es', createTranslator('es'))).toBe(STRATEGY_CATALOG[3]);
        en(<StrategySelector strategies={[catalog[1]]} currentStrategy="value" catalog={catalog} />);
        expect(screen.getByText('Strategy:')).toBeTruthy();
        expect(screen.getByRole('combobox', { name: 'Strategy' })).toBeTruthy();
    });
});
