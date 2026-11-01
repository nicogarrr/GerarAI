import { describe, expect, it } from 'vitest';
import { availableIndicators, barsSince, detectMovements, eventsInRange, movementEvents, indicatorSeries, markersByDay, volumeSpikeFlags, type PriceEvent } from '@/lib/market/price-events';

const day = (i: number) => new Date(Date.UTC(2026, 0, 1) + i * 86_400_000).toISOString().slice(0, 10);

describe('Precio y eventos: cálculos del gráfico de la ficha', () => {
    it('marca el volumen ≥ 2,5× la media de las 60 sesiones anteriores', () => {
        const bars = Array.from({ length: 70 }, (_, i) => ({ date: day(i), close: 10, volume: 100 }));
        bars[65] = { ...bars[65], volume: 260 };
        bars[66] = { ...bars[66], volume: 240 };
        const flags = volumeSpikeFlags(bars);
        expect(flags[65]).toBe(true);
        expect(flags[66]).toBe(false);
        expect(flags[5]).toBe(false); // sin historia suficiente no se marca
    });

    it('calcula distancia al objetivo, caída desde máximo y plusvalía en %', () => {
        const bars = [{ date: day(0), close: 100, high: 120 }, { date: day(1), close: 90, high: 95 }];
        expect(indicatorSeries(bars, 'target', { target: 135 }).map((p) => p.value)).toEqual([35, 50]);
        expect(indicatorSeries(bars, 'drawdown', {}).map((p) => p.value)).toEqual([-16.67, -25]);
        expect(indicatorSeries(bars, 'pnl', { averageCost: 80 }).map((p) => p.value)).toEqual([25, 12.5]);
        expect(indicatorSeries(bars, 'target', { target: null })).toEqual([]);
    });

    it('solo ofrece los indicadores que tienen datos', () => {
        expect(availableIndicators({})).toEqual(['drawdown']);
        expect(availableIndicators({ target: 50, averageCost: 40 })).toEqual(['target', 'drawdown', 'pnl']);
    });

    it('filtra eventos al tramo visible, más recientes primero, y junta los días con varios', () => {
        const events: PriceEvent[] = [
            { id: 'a', date: '2026-03-01', kind: 'results', title: 'Resultados', source: 'NASDAQ' },
            { id: 'b', date: '2026-03-01', kind: 'news', title: 'Noticia', source: 'Reuters' },
            { id: 'c', date: '2026-04-10', kind: 'ex_dividend', title: 'Ex-dividendo', source: 'fmp' },
            { id: 'd', date: '2025-12-01', kind: 'filing', title: '10-Q', source: 'SEC' },
        ];
        const inRange = eventsInRange(events, '2026-01-01', '2026-06-30');
        expect(inRange.map((e) => e.id)).toEqual(['c', 'b', 'a']);
        const markers = markersByDay(inRange, new Set());
        expect(markers).toHaveLength(2);
        expect(markers[0]).toMatchObject({ date: '2026-03-01', count: 2, text: '2', kinds: ['results', 'news'] });
        expect(markersByDay(inRange, new Set(['news']))[0]).toMatchObject({ count: 1, text: 'R' });
    });

    it('«Desde compra» empieza en la fecha de la primera compra', () => {
        const bars = [{ date: '2024-01-02' }, { date: '2024-03-04' }, { date: '2024-05-06' }];
        expect(barsSince(bars, '2024-03-04').map((b) => b.date)).toEqual(['2024-03-04', '2024-05-06']);
        expect(barsSince(bars, null)).toHaveLength(3);
    });

    it('¿Por qué se movió?: detecta movimientos y dice qué pasó o «Sin noticias ese día», sin afirmar la causa', () => {
        const bars = Array.from({ length: 40 }, (_, i) => ({ date: day(i), close: 100 * (1 + (i % 2 ? 0.005 : -0.005)), volume: 1000 }));
        bars[30] = { date: day(30), close: bars[29].close * 1.06, volume: 1000 }; // +6 %: supera 4 % y 2,5 σ
        bars[35] = { date: day(35), close: bars[34].close, volume: 3000 }; // solo volumen 3×
        const moves = detectMovements(bars);
        expect(moves.map((m) => [m.date, m.byPrice, m.byVolume])).toEqual([[day(30), true, false], [day(31), true, false], [day(35), false, true]]);
        const news: PriceEvent[] = [{ id: 'n', date: day(29), kind: 'news', title: 'Sube la guía', source: 'Reuters' }];
        const [first, , third] = movementEvents(moves, news);
        expect(first.kind).toBe('movement');
        expect(first.title).toContain('+6,0 %');
        expect(first.detail).toContain('Puede explicarlo');
        expect(first.detail).toContain('Sube la guía (Reuters)');
        expect(third.title).toContain('volumen 3× la media');
        expect(third.detail).toMatch(/^Sin noticias ese día/);
        expect(`${first.title}${first.detail}`).not.toMatch(/porque|causa|debido/i);
    });
});
