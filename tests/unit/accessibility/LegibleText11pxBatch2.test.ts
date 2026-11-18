/**
 * Auditoría 18-nov-2026: tercer lote de texto de lectura a 11 px, por debajo
 * del suelo de la casa (text-xs / 12 px, guard legible-text-guard de la
 * auditoría 11-nov). Sube a text-xs:
 *
 * - risk/RiskDashboardView: cabeceras de la tabla de posiciones (nombre,
 *   sector, valor y peso).
 * BottomNav queda FUERA: a 320 px las etiquetas «Descubrir»/«Watchlist»
 *   colisionan a 12 px (medido con captura real; celdas de ~53 px). Se
 *   conserva a 11 px sin regresión y su subida va en parche aparte con
 *   carve-out responsive (min-[360px]:text-xs). Aquí solo se guarda que el
 *   área táctil min-h-14 (56 px) sigue intacta.
 * - proPicks: nota «verificado» de MonthlyRebalanceView; pies de
 *   WalkForwardResults y StrategyFactsheet; disclaimer de DcaBacktestPanel;
 *   badges de estado de unified/TrackingView y unified/OpportunitiesView;
 *   sufijo «/100» y fuente de la razón de GemsView; nota de
 *   EnhancedProPicksContent.
 *
 * Sin excepciones: tras este lote ninguno de los 10 archivos conserva texto
 * a 9, 10 u 11 px. GemsView y EnhancedProPicksContent ya tenían vedados 9 y
 * 10 px por ProPicksResearchSmallText (#5875); aquí se les añade el 11 px.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const ROOT = join(__dirname, '..', '..', '..');

function src(path: string): string {
    return readFileSync(join(ROOT, path), 'utf8');
}

const FILES = [
    'components/risk/RiskDashboardView.tsx',
    'components/proPicks/MonthlyRebalanceView.tsx',
    'components/proPicks/WalkForwardResults.tsx',
    'components/proPicks/StrategyFactsheet.tsx',
    'components/proPicks/DcaBacktestPanel.tsx',
    'components/proPicks/unified/TrackingView.tsx',
    'components/proPicks/unified/OpportunitiesView.tsx',
    'components/proPicks/GemsView.tsx',
    'components/proPicks/EnhancedProPicksContent.tsx',
];

describe('texto legible lote 11 px (2): nada de lectura bajo 12 px', () => {
    it.each(FILES)('%s no tiene texto a 11 px', (path) => {
        expect(src(path)).not.toContain('text-[11px]');
    });

    it.each(FILES)('%s no tiene texto a 10 px', (path) => {
        expect(src(path)).not.toContain('text-[10px]');
    });

    it.each(FILES)('%s no tiene texto a 9 px', (path) => {
        expect(src(path)).not.toContain('text-[9px]');
    });

    it('RiskDashboardView sube las 4 cabeceras de posiciones a text-xs', () => {
        const s = src('components/risk/RiskDashboardView.tsx');
        expect(s.match(/text-xs uppercase tracking-wide text-gray-500/g)?.length ?? 0).toBe(4);
    });

    it('BottomNav mantiene el área táctil min-h-14 (la etiqueta sube en parche aparte)', () => {
        const s = src('components/layout/BottomNav.tsx');
        expect(s.match(/min-h-14/g)?.length ?? 0).toBeGreaterThanOrEqual(2);
    });

    it('los badges de estado de tracking y oportunidades suben a text-xs', () => {
        expect(src('components/proPicks/unified/TrackingView.tsx')).toContain('px-2 py-0.5 text-xs text-amber-300');
        expect(src('components/proPicks/unified/OpportunitiesView.tsx')).toContain('px-2 py-0.5 text-xs ${');
    });
});
