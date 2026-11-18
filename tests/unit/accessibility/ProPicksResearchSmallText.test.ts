/**
 * Auditoría 18-nov-2026: texto de lectura a 10 px en proPicks, research y
 * componentes comunes, por debajo del suelo de la casa (text-xs / 12 px,
 * guard legible-text-guard de la auditoría 11-nov).
 *
 * - proPicks: nota N/D de categorías, etiqueta de puntuación de gemas,
 *   etiqueta «sin datos» del selector de estrategia.
 * - research: etiquetas de estadísticas y consenso de AnalystHistoryView;
 *   enlace TradingView, etiqueta y detalle de Metric del gráfico técnico;
 *   nota de volumen, tag de tipo, fuente y botón «detalle» de PriceEventsPanel.
 * - common: nota de divisa de AnalystTargetLine y Tag de ExtendedHoursLine.
 *
 * Quedan fuera los marcadores tipográficos (sup «*») y los badges de estado.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const ROOT = join(__dirname, '..', '..', '..');

function src(path: string): string {
    return readFileSync(join(ROOT, path), 'utf8');
}

describe('texto legible en proPicks, research y common: nada de lectura bajo 12 px', () => {
    it.each([
        'components/proPicks/EnhancedProPicksContent.tsx',
        'components/proPicks/GemsView.tsx',
        'components/proPicks/StrategySelector.tsx',
        'components/research/AnalystHistoryView.tsx',
        'components/research/CompanyTechnicalChart.tsx',
        'components/research/PriceEventsPanel.tsx',
        'components/common/AnalystTargetLine.tsx',
        'components/common/ExtendedHoursLine.tsx',
    ])('%s no tiene texto de lectura a 10 px', (path) => {
        expect(src(path)).not.toContain('text-[10px]');
    });

    it('PriceEventsPanel sube fuente, tag y detalle a text-xs', () => {
        const s = src('components/research/PriceEventsPanel.tsx');
        expect(s.match(/text-xs text-gray-500/g)?.length ?? 0).toBeGreaterThanOrEqual(3);
        expect(s).toContain('rounded px-1 text-xs font-semibold');
        expect(s).toContain('text-xs text-gray-500 hover:text-gray-200');
    });

    it('CompanyTechnicalChart sube Metric y el enlace TradingView a text-xs', () => {
        const s = src('components/research/CompanyTechnicalChart.tsx');
        expect(s).toContain('<dt className="text-xs text-gray-500">{label}</dt>');
        expect(s).toContain('mt-1 text-xs leading-4 text-gray-500');
        expect(s).toContain('items-center text-xs text-gray-500 underline">TradingView');
    });
});
