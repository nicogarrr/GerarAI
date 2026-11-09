import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

// Guardia de regresión: con el minBarSpacing por defecto de lightweight-charts
// (0,5 px), fitContent() solo puede encajar ~664 barras en un gráfico de 332 px.
// En los rangos 5A (1.256 sesiones) y Máx (11.569 sesiones, desde 1980) el
// gráfico mostraba en silencio solo los últimos ~2 años mientras el pie de
// rango anunciaba «12 dic 1980 – 6 nov 2026 · 11569 sesiones»: el usuario
// creía ver todo el historial y veía una fracción. Con minBarSpacing: 0.001
// fitContent encaja el historial completo, como hace TradingView.
const SOURCE = readFileSync('components/research/CompanyTechnicalChart.tsx', 'utf8');

describe('el gráfico encaja todo el historial en 5A/Máx', () => {
    it('relaja minBarSpacing para que fitContent no trunque rangos largos', () => {
        const timeScale = SOURCE.match(/timeScale: \{[^}]+\}/);
        expect(timeScale, 'opciones del eje de tiempo encontradas').toBeTruthy();
        expect(timeScale![0]).toContain('minBarSpacing: 0.001');
        // Se conserva el resto de la configuración del eje.
        expect(timeScale![0]).toContain('rightOffset: 6');
        expect(timeScale![0]).toContain('borderVisible: false');
    });

    it('sigue llamando a fitContent tras cargar los datos', () => {
        expect(SOURCE).toContain('current.chart.timeScale().fitContent()');
    });
});
