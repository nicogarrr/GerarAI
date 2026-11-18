import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

// Lote DCA del suelo de lectura (12 px, auditoría 11-nov): las etiquetas
// informativas de la familia DCA de watchlist seguían a 11 px — explicador
// y notas de la tarjeta de aciertos, cabeceras de su tabla, badges de
// señal/horizonte, nota del panel de señales y botones de despliegue. No
// hay marcadores tipográficos en esta familia: todo es lectura, así que la
// regla es 0 ocurrencias de text-[11px] y text-[10px] en los seis ficheros.

const FILES = [
    'components/watchlist/DcaHitRatesCard.tsx',
    'components/watchlist/DcaWatchCard.tsx',
    'components/watchlist/DcaLevelBadge.tsx',
    'components/watchlist/DcaWatchCardToggle.tsx',
    'components/watchlist/DcaSignalsPanel.tsx',
    'components/watchlist/DcaHitRatesPopover.tsx',
];

const src = (p: string) => readFileSync(p, 'utf8');

describe('texto legible lote DCA: nada de lectura bajo 12 px', () => {
    it.each(FILES)('%s no tiene texto a 11 px ni 10 px', (path) => {
        const s = src(path);
        expect(s.match(/text-\[11px\]/g) ?? [], 'queda text-[11px]').toHaveLength(0);
        expect(s.match(/text-\[10px\]/g) ?? [], 'queda text-[10px]').toHaveLength(0);
    });

    it('el explicador de la tarjeta de aciertos va a 12 px', () => {
        const s = src('components/watchlist/DcaHitRatesCard.tsx');
        expect(s).toContain('text-xs leading-4 text-gray-400" data-testid="dca-hit-rates-explainer"');
    });

    it('las cabeceras de la tabla de horizontes van a 12 px', () => {
        const s = src('components/watchlist/DcaHitRatesCard.tsx');
        expect(s).toContain('role="columnheader" className="px-1 text-left text-xs font-medium"');
    });

    it('el badge de nivel provisional va a 12 px conservando su zona táctil ampliada', () => {
        const s = src('components/watchlist/DcaLevelBadge.tsx');
        expect(s).toContain('before:-inset-2.5');
        expect(s).toContain('text-xs font-semibold whitespace-nowrap');
    });
});
