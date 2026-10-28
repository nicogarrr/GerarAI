import { describe, expect, it } from 'vitest';
import type { ProPick } from '@/lib/actions/proPicks.actions';
import {
    STRATEGY_CATALOG,
    buildMonthlySnapshot,
    diffSnapshots,
    mergeStrategies,
    monthKey,
    monthLabelEs,
    pickReason,
    pickReasons,
    toSnapshotPick,
    type MonthlySnapshot,
} from '@/components/proPicks/monthlyRebalance';

const pick = (over: Record<string, unknown> = {}): ProPick =>
    ({
        symbol: 'AAPL',
        company: 'Apple',
        score: 75.4,
        grade: 'B+',
        categoryScores: { value: 60, growth: 70, profitability: 80, cashFlow: 65, momentum: 55, debtLiquidity: 50 },
        reasons: [],
        confidenceReasons: [],
        confidence: 72,
        confidenceLevel: 'Media',
        asOf: '2026-10-27',
        facts: { return12M: 12 },
        ...over,
    }) as unknown as ProPick;

describe('mergeStrategies', () => {
    it('devuelve las 4 estrategias del catálogo y marca como no disponibles las que el servidor no da', () => {
        const merged = mergeStrategies([{ id: 'value', name: 'Value Pro', description: 'Texto del servidor' }]);
        expect(merged.map((s) => s.id)).toEqual(STRATEGY_CATALOG.map((s) => s.id));
        expect(merged.find((s) => s.id === 'value')).toEqual({
            id: 'value',
            name: 'Value Pro',
            description: 'Texto del servidor',
            available: true,
        });
        expect(merged.filter((s) => s.available)).toHaveLength(1);
        expect(merged.find((s) => s.id === 'momentum')?.available).toBe(false);
    });

    it('si el servidor manda nombre o descripción vacíos conserva los del catálogo', () => {
        const [adaptive] = mergeStrategies([{ id: 'adaptive', name: '', description: '' }]);
        expect(adaptive.name).toBe(STRATEGY_CATALOG[0].name);
        expect(adaptive.description).toBe(STRATEGY_CATALOG[0].description);
        expect(adaptive.available).toBe(true);
    });

    it('sin estrategias del servidor todas quedan sin datos', () => {
        expect(mergeStrategies([]).every((s) => !s.available)).toBe(true);
    });
});

describe('pickReason / pickReasons', () => {
    it('prioriza el overlay con texto sobre confidenceReasons', () => {
        const p = pick({
            confidenceReasons: [{ text: 'Sube un 12% en 12 meses', metric: 'return12M', value: 12 }],
            overlays: [{ metric: 'ov_insider', value: 3, detail: 'Compras de insiders' }],
        });
        expect(pickReason(p)).toEqual({ text: 'Compras de insiders', metric: 'ov_insider', value: 3 });
    });

    it('un overlay sin texto utilizable se ignora y se usa el primer confidenceReason', () => {
        const p = pick({
            confidenceReasons: [{ text: 'Liquidez sólida (ratio 2.4)', metric: 'currentRatio', value: 2.4 }],
            overlays: [{ metric: 'ov_vix', value: 18, detail: '' }],
        });
        expect(pickReason(p)).toEqual({ text: 'Liquidez sólida (ratio 2.4)', metric: 'currentRatio', value: 2.4 });
    });

    it('lee texto de los campos alternativos del overlay y descarta metric/value de tipo raro', () => {
        const p = pick({ overlays: [{ reason: 'Revisiones al alza', metric: 5, value: { x: 1 } }] });
        expect(pickReason(p)).toEqual({ text: 'Revisiones al alza', metric: undefined, value: undefined });
        expect(pickReason(pick({ overlays: [{ label: 'Etiqueta', value: 'alto' }] }))).toEqual({
            text: 'Etiqueta',
            metric: undefined,
            value: 'alto',
        });
        expect(pickReason(pick({ overlays: [{ text: 'Texto' }] })).text).toBe('Texto');
    });

    it('sin overlays ni motivos cae en una frase con score redondeado y confianza, sin inventar métricas', () => {
        const reason = pickReason(pick());
        expect(reason.text).toBe('Score 75/100 con confianza Media');
        expect(reason.metric).toBeUndefined();
        expect(reason.value).toBeUndefined();
    });

    it('overlays no array se tratan como vacíos', () => {
        expect(pickReason(pick({ overlays: 'raro' })).text).toContain('Score 75/100');
    });

    it('pickReasons junta motivos, no duplica textos, ignora vacíos y limita a 4', () => {
        const p = pick({
            confidenceReasons: [
                { text: 'A', metric: 'a', value: 1 },
                { text: '', metric: 'x', value: 0 },
                { text: 'B', metric: 'b', value: 2 },
            ],
            overlays: [
                { detail: 'A', metric: 'ov_a' },
                { detail: 'C', metric: 'ov_c', value: 3 },
                { detail: 'D' },
                { detail: 'E' },
                { metric: 'sin-texto' },
            ],
        });
        const reasons = pickReasons(p);
        expect(reasons.map((r) => r.text)).toEqual(['A', 'B', 'C', 'D']);
        expect(reasons[2]).toEqual({ text: 'C', metric: 'ov_c', value: 3 });
    });

    it('pickReasons sin nada devuelve lista vacía', () => {
        expect(pickReasons(pick())).toEqual([]);
        expect(pickReasons({ ...pick(), confidenceReasons: undefined } as unknown as ProPick)).toEqual([]);
    });
});

describe('meses', () => {
    it('monthKey rellena el mes con cero', () => {
        expect(monthKey(new Date(2026, 8, 15))).toBe('2026-09');
        expect(monthKey(new Date(2027, 0, 1))).toBe('2027-01');
        expect(monthKey()).toMatch(/^\d{4}-\d{2}$/);
    });

    it('monthLabelEs devuelve el mes en español y tolera entradas rotas', () => {
        expect(monthLabelEs('2026-09').toLowerCase()).toContain('septiembre');
        expect(monthLabelEs('2026-09')).toContain('2026');
        expect(monthLabelEs('basura')).toBe('basura');
        expect(monthLabelEs('2026-00')).toBe('2026-00');
    });
});

describe('snapshot mensual', () => {
    it('toSnapshotPick copia facts (sin compartir referencia) y los motivos trazables', () => {
        const p = pick({ confidenceReasons: [{ text: 'Motivo', metric: 'm', value: 1 }] });
        const snap = toSnapshotPick(p);
        expect(snap).toMatchObject({
            symbol: 'AAPL',
            company: 'Apple',
            score: 75.4,
            confidence: 72,
            confidenceLevel: 'Media',
            asOf: '2026-10-27',
            reasons: [{ text: 'Motivo', metric: 'm', value: 1 }],
        });
        expect(snap.facts).toEqual({ return12M: 12 });
        expect(snap.facts).not.toBe(p.facts);
        expect(toSnapshotPick({ ...p, facts: undefined } as unknown as ProPick).facts).toEqual({});
    });

    it('buildMonthlySnapshot usa mes y fecha dados y etiqueta el tipo/versión', () => {
        const snap = buildMonthlySnapshot([pick()], 'value', '2026-10', '2026-10-28T00:00:00.000Z');
        expect(snap).toMatchObject({
            kind: 'cavaai-propicks-monthly-snapshot',
            version: 1,
            month: '2026-10',
            strategyId: 'value',
            generatedAt: '2026-10-28T00:00:00.000Z',
        });
        expect(snap.picks).toHaveLength(1);
        const auto = buildMonthlySnapshot([], 'adaptive');
        expect(auto.month).toMatch(/^\d{4}-\d{2}$/);
        expect(Number.isNaN(Date.parse(auto.generatedAt))).toBe(false);
    });
});

describe('diffSnapshots', () => {
    const msft = pick({ symbol: 'MSFT', company: 'Microsoft' });
    const previous = (symbols: Array<[string, string]>): MonthlySnapshot => ({
        kind: 'cavaai-propicks-monthly-snapshot',
        version: 1,
        month: '2026-09',
        strategyId: 'adaptive',
        generatedAt: '2026-09-30T00:00:00.000Z',
        picks: symbols.map(([symbol, company]) => ({
            symbol,
            company,
            score: 70,
            confidence: 70,
            confidenceLevel: 'Media',
            reasons: [],
            facts: {},
            asOf: '2026-09-30',
        })),
    });

    it('sin snapshot previo todo entra y hasPrevious es false', () => {
        for (const prev of [null, undefined, { picks: 'x' } as unknown as MonthlySnapshot]) {
            const diff = diffSnapshots([pick(), msft], prev);
            expect(diff.hasPrevious).toBe(false);
            expect(diff.entered.map((m) => m.symbol)).toEqual(['AAPL', 'MSFT']);
            expect(diff.exited).toEqual([]);
            expect(diff.kept).toEqual([]);
        }
    });

    it('separa entran, salen y se mantienen; el motivo de salida sale del snapshot previo', () => {
        const prev = previous([['AAPL', 'Apple'], ['TSLA', 'Tesla']]);
        prev.picks[1].reasons = [{ text: 'Momentum fuerte', metric: 'momentum', value: 90 }];
        const diff = diffSnapshots([pick(), msft], prev);
        expect(diff.hasPrevious).toBe(true);
        expect(diff.kept).toEqual(['AAPL']);
        expect(diff.entered.map((m) => m.symbol)).toEqual(['MSFT']);
        expect(diff.exited).toEqual([
            { symbol: 'TSLA', company: 'Tesla', reason: { text: 'Momentum fuerte', metric: 'momentum', value: 90 } },
        ]);
    });

    it('un valor que sale sin motivo guardado lo dice sin inventar números', () => {
        const diff = diffSnapshots([pick()], previous([['AAPL', 'Apple'], ['KO', 'Coca-Cola']]));
        expect(diff.exited[0].reason).toEqual({ text: 'Estaba en la selección del mes anterior' });
    });
});

