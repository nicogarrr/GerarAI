import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { MARKERS_MAX_BARS, markersForBars } from '@/lib/market/price-events';

// Con el eje completo de Máx (fix minBarSpacing), 11.569 sesiones en ~330 px
// son 34 barras por píxel: los marcadores de eventos se fundían en una banda
// rosa continua que tapaba la línea de precio. A partir de MARKERS_MAX_BARS
// el canvas va sin marcadores y el detalle se consulta en la lista
// «Eventos del período», que sigue mostrándolos todos (no se oculta dato).
describe('markersForBars: sin banda de marcadores en tramos muy largos', () => {
    const markers = [{ date: '2026-01-01' }, { date: '2026-02-01' }];

    it('conserva los marcadores hasta 5A (1.256 barras)', () => {
        expect(markersForBars(markers, 1256)).toBe(markers);
    });

    it('los omite en Máx (11.569 barras): banda ilegible sobre el precio', () => {
        expect(markersForBars(markers, 11569)).toEqual([]);
    });

    it('el corte es exactamente MARKERS_MAX_BARS (1500)', () => {
        expect(MARKERS_MAX_BARS).toBe(1500);
        expect(markersForBars(markers, MARKERS_MAX_BARS)).toBe(markers);
        expect(markersForBars(markers, MARKERS_MAX_BARS + 1)).toEqual([]);
    });

    it('sin marcadores de entrada no rompe', () => {
        expect(markersForBars([], 20000)).toEqual([]);
    });
});

describe('el canvas aplica el recorte de marcadores', () => {
    const SOURCE = readFileSync('components/research/CompanyTechnicalChart.tsx', 'utf8');

    it('seriesMarkers pasa por markersForBars con el número de barras', () => {
        expect(SOURCE).toContain('markersForBars(markers, bars.length)');
    });

    it('los marcadores siguen vacíos en intradía', () => {
        expect(SOURCE).toMatch(/seriesMarkers: SeriesMarker<Time>\[\] = hourly \? \[\] :/);
    });
});
