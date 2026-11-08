import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

// Guardia de regresión: a 390 px los 8 botones de rango del gráfico de la
// ficha no cabían en una fila (8 x min-w-11 + huecos = 380 px > 358 px) y
// «Máx» quedaba huérfano en su propia línea. La base ~21% con flex-1 los
// reparte en dos filas parejas de 4; desde sm no cambia nada.
const SOURCE = readFileSync('components/research/CompanyTechnicalChart.tsx', 'utf8');

describe('botones de rango del gráfico en móvil', () => {
    it('se reparten en filas parejas en vez de dejar «Máx» huérfano', () => {
        const rangeButton = SOURCE.match(/CHART_RANGES\.map\(\(value\) => <button[^]*?className=\{`([^`]+)\$\{/);
        expect(rangeButton, 'botón de rango encontrado').toBeTruthy();
        expect(rangeButton![1]).toContain('flex-1');
        expect(rangeButton![1]).toContain('basis-[21%]');
        expect(rangeButton![1]).toContain('sm:basis-auto');
        // La diana táctil de 44 px no se toca.
        expect(rangeButton![1]).toContain('min-h-11');
        expect(rangeButton![1]).toContain('min-w-11');
    });

    it('la fila de rangos sigue envolviendo (flex-wrap)', () => {
        expect(SOURCE).toContain('aria-label={t(\'research.chart.rangeAria\')}');
        expect(SOURCE).toMatch(/className="flex w-full flex-wrap gap-1 sm:w-auto"/);
    });
});
