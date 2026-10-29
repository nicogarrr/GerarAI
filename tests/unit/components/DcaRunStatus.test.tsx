import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }) }));
vi.mock('@/lib/actions/dca-signals.actions', () => ({
    evaluateDcaSignalsNow: vi.fn(),
    getDcaHitRates: vi.fn(),
}));

import DcaLevelBadge from '@/components/watchlist/DcaLevelBadge';
import DcaSignalsPanel from '@/components/watchlist/DcaSignalsPanel';
import { dcaMissingBadge, dcaRunSummary } from '@/lib/dca/format';
import type { DcaRun, DcaSignalItem, DcaSignalsResponse } from '@/lib/dca/types';

function item(extra: Partial<DcaSignalItem> = {}): DcaSignalItem {
    return {
        symbol: 'UBER',
        company_name: 'Uber',
        sources: ['portfolio'],
        in_watchlist: false,
        in_portfolio: true,
        min_level_override: null,
        effective_min_level: 2,
        alerts_on: false,
        state: null,
        ...extra,
    };
}

const run = (extra: Partial<DcaRun> = {}): DcaRun => ({
    status: 'ok',
    trigger: 'scheduler',
    started_at: '2026-10-27T23:15:00Z',
    finished_at: '2026-10-27T23:16:00Z',
    tracked: 19,
    evaluated: 19,
    skipped: 0,
    errors: 0,
    alerted: 0,
    error: null,
    ...extra,
});

function panel(items: DcaSignalItem[], last_run: DcaRun | null | undefined): DcaSignalsResponse {
    return {
        alerts_enabled: false,
        evaluation_enabled: true,
        global_min_level: 2,
        trims_enabled: false,
        channels: ['in_app'],
        email_configured: false,
        signal_months: 30,
        zones: [],
        items,
        ...(last_run === undefined ? {} : { last_run }),
    };
}

describe('dcaMissingBadge', () => {
    it('fallo del job: mensaje genérico del backend sin doble punto', () => {
        const generic = 'No se pudo completar la evaluación DCA. Reintenta más tarde.';
        const badge = dcaMissingBadge(item({ evaluation_status: 'job_failed', evaluation_reason: generic }));
        expect(badge.text).toBe('Evaluación fallida');
        expect(badge.title).toBe(`La última evaluación falló para este ticker: ${generic}`);
        expect(badge.title).not.toContain('..');
    });

    it('sin información del backend se trata como nunca ejecutado', () => {
        expect(dcaMissingBadge(item()).text).toBe('Sin evaluar');
        expect(dcaMissingBadge(undefined).text).toBe('Sin evaluar');
    });
    it('distingue fallo del job y omitido, con motivo', () => {
        const failed = dcaMissingBadge(item({ evaluation_status: 'job_failed', evaluation_reason: 'HTTPError' }));
        expect(failed).toMatchObject({ text: 'Evaluación fallida', tone: 'error' });
        expect(failed.title).toContain('HTTPError');
        const skipped = dcaMissingBadge(item({ evaluation_status: 'skipped', evaluation_reason: 'datos_desactualizados' }));
        expect(skipped.text).toBe('Omitido');
        expect(skipped.title).toContain('datos de precio demasiado viejos');
    });
});

describe('dcaMissingBadge con ejecución registrada', () => {
    it('nunca dice "Sin evaluar" si consta una ejecución: pendiente, desconocido o en curso', () => {
        expect(dcaMissingBadge(item({ evaluation_status: 'pending' })).text).toBe('Pendiente');
        const unknown = dcaMissingBadge(item({ evaluation_status: 'unknown', evaluation_reason: 'detalle truncado' }));
        expect(unknown).toMatchObject({ text: 'Estado desconocido', tone: 'warn' });
        expect(unknown.title).toContain('truncado');
        expect(dcaMissingBadge(item({ evaluation_status: 'running' })).text).toBe('En curso');
    });
});

describe('dcaRunSummary', () => {
    it('nunca ejecutado', () => {
        expect(dcaRunSummary(null)).toMatchObject({ tone: 'neutral' });
        expect(dcaRunSummary(null).text).toContain('ninguna registrada');
    });
    it('ok completo, parcial, fallo e interrumpida', () => {
        expect(dcaRunSummary(run())).toMatchObject({ tone: 'ok' });
        expect(dcaRunSummary(run()).text).toContain('19 de 19 evaluados');
        const partial = dcaRunSummary(run({ evaluated: 17, skipped: 1, errors: 1 }));
        expect(partial.tone).toBe('warn');
        expect(partial.text).toContain('1 omitidos');
        expect(partial.text).toContain('1 con error');
        expect(dcaRunSummary(run({ status: 'error', error: 'RuntimeError: x' }))).toMatchObject({ tone: 'error' });
        expect(dcaRunSummary(run({ status: 'interrupted' })).text).toContain('interrumpida');
        expect(dcaRunSummary(run({ status: 'running', finished_at: null })).text).toContain('en curso');
    });
});

describe('DcaLevelBadge sin nivel', () => {
    it('pinta el estado real del ticker', () => {
        render(<DcaLevelBadge item={item({ evaluation_status: 'job_failed', evaluation_reason: 'boom' })} signalMonths={30} />);
        expect(screen.getByTestId('dca-missing-badge').textContent).toBe('Evaluación fallida');
    });
    it('compacto no pinta nada', () => {
        const { container } = render(<DcaLevelBadge item={item()} signalMonths={30} compact />);
        expect(container.textContent).toBe('');
    });
});

describe('DcaSignalsPanel última ejecución', () => {
    it('muestra la última ejecución', () => {
        render(<DcaSignalsPanel data={panel([item()], run({ evaluated: 18, skipped: 1 }))} unavailable={false} />);
        expect(screen.getByTestId('dca-last-run').textContent).toContain('18 de 19 evaluados, 1 omitidos');
    });
    it('null = nunca ejecutado; ausente (backend viejo) = no inventa nada', () => {
        const { unmount } = render(<DcaSignalsPanel data={panel([item()], null)} unavailable={false} />);
        expect(screen.getByTestId('dca-last-run').textContent).toContain('ninguna registrada');
        unmount();
        render(<DcaSignalsPanel data={panel([item()], undefined)} unavailable={false} />);
        expect(screen.queryByTestId('dca-last-run')).toBeNull();
    });
});
