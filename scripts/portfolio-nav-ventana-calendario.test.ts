/**
 * Ventana del NAV de cartera por CALENDARIO, no por número de puntos.
 *
 * Las fotos de cartera solo existen los días con refresco (sin fines de
 * semana, con huecos), así que «los últimos 30 puntos» no es «1M».
 * Ejecución: node --experimental-strip-types --test scripts/portfolio-nav-ventana-calendario.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { windowNav } from '../lib/portfolio-nav.ts';

const DAY = 86_400_000;
const iso = (ms: number) => new Date(ms).toISOString().slice(0, 10);

describe('windowNav: golden con fotos semanales', () => {
    // 10 fotos, una por lunes: 2026-01-05 … 2026-03-09 (63 días de punta a punta).
    const start = Date.parse('2026-01-05T00:00:00Z');
    const dates = Array.from({ length: 10 }, (_, i) => iso(start + i * 7 * DAY));
    const nav = dates.map((_, i) => 100 + i);

    it('1M = fotos con menos de 30 días hasta la última (a mano: 0, 7, 14, 21 y 28 días → 5)', () => {
        // Antes: min(10, 30 puntos) = las 10 fotos, 2 meses pintados como «1M».
        const out = windowNav(dates, nav, '1M');
        assert.deepEqual(out.map((p) => p.date), ['2026-02-09', '2026-02-16', '2026-02-23', '2026-03-02', '2026-03-09']);
        assert.deepEqual(out.map((p) => p.value), [105, 106, 107, 108, 109]);
    });

    it('1S = solo la última foto (la anterior está a 7 días, fuera)', () => {
        assert.deepEqual(windowNav(dates, nav, '1S'), [{ date: '2026-03-09', value: 109 }]);
    });

    it('3M, 1A y Todo cubren las 10 fotos (63 días < 90)', () => {
        for (const period of ['3M', '1A', 'Todo']) assert.equal(windowNav(dates, nav, period).length, 10);
    });

    it('YTD = las fotos del año de la última (todas son de 2026)', () => {
        assert.equal(windowNav(dates, nav, 'YTD').length, 10);
    });
});

describe('windowNav: golden con días hábiles', () => {
    // Lunes a viernes de 2026-01-05 a 2026-03-31: 1M desde el 2026-03-02 (29 días antes).
    const dates: string[] = [];
    for (let ms = Date.parse('2026-01-05T00:00:00Z'); ms <= Date.parse('2026-03-31T00:00:00Z'); ms += DAY) {
        const wd = new Date(ms).getUTCDay();
        if (wd !== 0 && wd !== 6) dates.push(iso(ms));
    }
    const nav = dates.map(() => 1);

    it('1M arranca el 2 de marzo: 22 días hábiles, no 30 puntos', () => {
        const out = windowNav(dates, nav, '1M');
        assert.equal(out[0].date, '2026-03-02');
        assert.equal(out.length, 22);
    });
});

describe('windowNav: propiedades (200 casos, semilla fija)', () => {
    // LCG determinista: misma secuencia en cada ejecución.
    let seed = 20261027;
    const rand = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
    const periods = ['1S', '1M', '3M', '6M', 'YTD', '1A', 'Todo'];
    const counts: Record<string, number> = { '1S': 7, '1M': 30, '3M': 90, '6M': 180, '1A': 365 };

    it('serie diaria sin huecos: idéntica a «los últimos N puntos» de antes', () => {
        for (let k = 0; k < 200; k++) {
            const n = 1 + Math.floor(rand() * 800);
            const first = Date.parse('2024-01-01T00:00:00Z') + Math.floor(rand() * 700) * DAY;
            const dates = Array.from({ length: n }, (_, i) => iso(first + i * DAY));
            const nav = dates.map(() => (rand() < 0.1 ? null : 100 * rand()));
            for (const period of periods) {
                let size: number;
                if (period === 'Todo') size = n;
                else if (period === 'YTD') size = dates.filter((d) => d.slice(0, 4) === dates[n - 1].slice(0, 4)).length;
                else size = Math.min(n, counts[period]);
                const expected = dates.slice(n - size).flatMap((date, i) => {
                    const value = nav[n - size + i];
                    return value == null ? [] : [{ date, value }];
                });
                assert.deepEqual(windowNav(dates, nav, period), expected, `${period} n=${n}`);
            }
        }
    });

    it('serie con huecos: todo punto devuelto cae en la ventana y ninguno es null', () => {
        for (let k = 0; k < 200; k++) {
            const dates: string[] = [];
            let ms = Date.parse('2025-01-01T00:00:00Z');
            const n = 1 + Math.floor(rand() * 300);
            for (let i = 0; i < n; i++) {
                dates.push(iso(ms));
                ms += (1 + Math.floor(rand() * 6)) * DAY;
            }
            const nav = dates.map(() => (rand() < 0.15 ? null : 50 + rand()));
            const last = Date.parse(`${dates[n - 1]}T00:00:00Z`);
            for (const period of ['1S', '1M', '3M', '6M', '1A']) {
                const out = windowNav(dates, nav, period);
                for (const p of out) {
                    assert.ok((last - Date.parse(`${p.date}T00:00:00Z`)) / DAY < counts[period], `${period} ${p.date}`);
                    assert.equal(typeof p.value, 'number');
                }
                const inside = dates.filter((d, i) => nav[i] != null && (last - Date.parse(`${d}T00:00:00Z`)) / DAY < counts[period]);
                assert.equal(out.length, inside.length, period);
            }
        }
    });
});
