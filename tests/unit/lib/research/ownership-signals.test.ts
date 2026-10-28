import { describe, expect, it } from 'vitest';
import {
    holderChangeLabel, holdersLines, holdersTone, insiderLines, insiderTone, ownershipMoney,
    type HoldersOwnershipBlock, type InsiderOwnershipBlock,
} from '@/lib/research/ownership-signals';

const side = { trades: 0, insiders: 0, shares: 0, value: 0 };
const insider = (over: Partial<Extract<InsiderOwnershipBlock, { status: 'ok' }>> = {}): InsiderOwnershipBlock => ({
    status: 'ok', window_days: 90, source: 'sec', buys: side, sells: side, net_value: 0, cluster_buying: false, last_date: null, reading: '', ...over,
});
const holders = (changes: Partial<Record<'new' | 'increased' | 'decreased' | 'closed', number>> = {}, over = {}): HoldersOwnershipBlock => ({
    status: 'ok', source: '13f', holders_count: 3, managers_with_data: 10, report_date: null, total_value_usd: null,
    changes: { new: 0, increased: 0, decreased: 0, closed: 0, ...changes }, top_holders: [], exited: [], limitations: [], ...over,
});

describe('tonos', () => {
    it('insiders: sin datos o pendiente -> neutro, nunca positivo', () => {
        expect(insiderTone({ status: 'sin_datos' })).toBe('neutro');
        expect(insiderTone({ status: 'pendiente' })).toBe('neutro');
    });
    it('insiders: compra en grupo manda aunque el saldo sea negativo; saldo decide si no', () => {
        expect(insiderTone(insider({ cluster_buying: true, net_value: -5 }))).toBe('positivo');
        expect(insiderTone(insider({ net_value: 10 }))).toBe('positivo');
        expect(insiderTone(insider({ net_value: -10 }))).toBe('negativo');
        expect(insiderTone(insider())).toBe('neutro');
    });
    it('13F: compara altas+aumentos contra reducciones+salidas', () => {
        expect(holdersTone(holders({ new: 1, increased: 1, decreased: 1 }))).toBe('positivo');
        expect(holdersTone(holders({ closed: 2, increased: 1 }))).toBe('negativo');
        expect(holdersTone(holders({ new: 1, closed: 1 }))).toBe('neutro');
        expect(holdersTone({ status: 'pendiente' })).toBe('neutro');
    });
});

describe('textos', () => {
    it('dinero en USD es-ES sin decimales', () => {
        expect(ownershipMoney(1234567)).toMatch(/^1\.234\.567\sUS\$$/);
    });
    it('holderChangeLabel con y sin cambio', () => {
        expect(holderChangeLabel('closed')).toBe('sale');
        expect(holderChangeLabel(null)).toBe('sin comparación');
        expect(holderChangeLabel(undefined)).toBe('sin comparación');
    });
    it('insiderLines sin datos usa el detalle o un texto por defecto', () => {
        expect(insiderLines({ status: 'sin_datos', detail: 'nada' })).toEqual(['nada']);
        expect(insiderLines({ status: 'pendiente' })).toEqual(['Sin datos de insiders.']);
    });
    it('insiderLines menciona plan 10b5-1 solo si hay y la última operación solo si existe', () => {
        const withPlan = insiderLines(insider({ sells: { ...side, trades: 2, insiders: 1, value: 1000, planned_10b5_1: 2 }, last_date: '2026-02-01' }));
        expect(withPlan[1]).toContain('(2 con plan 10b5-1)');
        expect(withPlan[2]).toContain('última operación 2026-02-01');
        const plain = insiderLines(insider());
        expect(plain[1]).not.toContain('10b5-1');
        expect(plain[2]).not.toContain('última');
    });
    it('holdersLines: sin datos, con fecha y valor, y salidas', () => {
        expect(holdersLines({ status: 'pendiente' })).toEqual(['Sin datos 13F.']);
        const lines = holdersLines(holders({ new: 1 }, { report_date: '2026-06-30', total_value_usd: 5000, exited: ['A', 'B'] }));
        expect(lines[0]).toContain('3 de 10 gestores');
        expect(lines[0]).toContain('13F de 2026-06-30');
        expect(lines[0]).toContain('por ');
        expect(lines[1]).toBe('Frente al trimestre anterior: 1 nuevas, 0 aumentan, 0 reducen, 0 salen.');
        expect(lines[2]).toBe('Salen: A, B.');
        expect(holdersLines(holders()).length).toBe(2);
        expect(holdersLines(holders())[0]).not.toContain('por ');
    });
});
