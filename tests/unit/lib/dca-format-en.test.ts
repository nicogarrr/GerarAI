import { describe, expect, it } from 'vitest';
import { dcaDataAge, dcaMissingBadge, dcaPercent, dcaRunSummary, dcaSignalMetric, dcaSkipReason, dcaStaleText, dcaStatusLabel } from '@/lib/dca/format';
import type { DcaRun, DcaSignalState } from '@/lib/dca/types';
import { createTranslator } from '@/lib/i18n/translate';

const en = createTranslator('en');
const run = (extra: Partial<DcaRun> = {}): DcaRun => ({
    status: 'ok', trigger: 'scheduler', started_at: '2026-10-27T23:15:00Z', finished_at: '2026-10-27T23:16:00Z',
    tracked: 19, evaluated: 17, skipped: 1, errors: 1, alerted: 0, error: null, ...extra,
});

describe('lib/dca/format en inglés', () => {
    it('resumen de la última ejecución con fecha y número en inglés', () => {
        expect(dcaRunSummary(null, en, 'en').text).toBe('Last run: none recorded yet');
        const summary = dcaRunSummary(run(), en, 'en');
        expect(summary.text).toMatch(/^Last run \(automatic, Oct 28, 12:16 ?AM\): 17 of 19 evaluated, 1 skipped, 1 with errors$/);
        expect(dcaRunSummary(run({ status: 'running', trigger: 'manual' }), en, 'en').text).toMatch(/^Evaluation \(manual\) running since /);
    });

    it('badges sin nivel, edad y estado', () => {
        expect(dcaMissingBadge(undefined, en).text).toBe('Not evaluated');
        expect(dcaMissingBadge({ symbol: 'X', evaluation_status: 'skipped', evaluation_reason: 'sin_datos' } as never, en).title).toBe('The evaluation skipped it: no price data.');
        expect(dcaSkipReason(null, en)).toBe('skipped');
        expect(dcaDataAge(0, en)).toBe('today');
        expect(dcaDataAge(3, en)).toBe('3 days ago');
        expect(dcaStaleText('1 day ago', en)).toBe('stale · 1 day ago');
        expect(dcaStatusLabel('confirmed', en)).toBe('confirmed');
    });

    it('métrica y porcentaje con formato inglés', () => {
        expect(dcaPercent(-0.1234, 'en')).toBe('-12.3%');
        const state = { metrics: { signal: 'sma_gap', sma_gap: -0.05 } } as unknown as DcaSignalState;
        expect(dcaSignalMetric(state, 30, en, 'en')).toEqual({ label: 'Distance below 30m average', value: '-5.0%' });
    });

    it('sin traductor sigue en español', () => {
        expect(dcaRunSummary(null).text).toBe('Última ejecución: ninguna registrada todavía');
        expect(dcaDataAge(3)).toBe('hace 3 días');
    });
});
