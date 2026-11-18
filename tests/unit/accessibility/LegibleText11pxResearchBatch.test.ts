import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

// Lote research/company del suelo de lectura (12 px, auditoría 11-nov):
// aviso «velas no disponibles», nota ámbar de posición, botones de rango y
// «desde compra», líneas de metadatos del gráfico (rango de fechas, cierre
// sin confirmar, nota fib), etiqueta y fechas de «Cierre anterior» en la
// cabecera, chips de filtro de eventos y pill superior de la landing. Todo
// es lectura informativa; los botones conservan su hit-area min-h-11/min-w-11.

const FILES = [
    'components/research/CompanyTechnicalChart.tsx',
    'components/research/CompanyHeaderQuote.tsx',
    'components/research/PriceEventsPanel.tsx',
    'components/landing/PublicLanding.tsx',
];

const src = (p: string) => readFileSync(p, 'utf8');

describe('texto legible lote research: nada de lectura bajo 12 px', () => {
    it.each(FILES)('%s no tiene texto a 11 px ni 10 px', (path) => {
        const s = src(path);
        expect(s.match(/text-\[11px\]/g) ?? [], 'queda text-[11px]').toHaveLength(0);
        expect(s.match(/text-\[10px\]/g) ?? [], 'queda text-[10px]').toHaveLength(0);
    });

    it('los botones de rango van a 12 px fijos conservando su zona táctil 44px', () => {
        const s = src('components/research/CompanyTechnicalChart.tsx');
        expect(s).toContain('min-h-11 min-w-11 flex-1 basis-[21%] rounded-md px-1 text-xs transition');
        expect(s).not.toContain('sm:text-xs');
    });

    it('el aviso de velas no disponibles va a 12 px', () => {
        const s = src('components/research/CompanyTechnicalChart.tsx');
        expect(s).toContain('text-xs text-gray-500">{t(\'research.chart.candlesUnavailable\')}</span>');
    });

    it('los chips de filtro de eventos van a 12 px conservando min-h-9', () => {
        const s = src('components/research/PriceEventsPanel.tsx');
        expect(s).toContain('inline-flex min-h-9 items-center gap-1 rounded-full border px-2 text-xs');
    });

    it('la pill superior de la landing va a 12 px fijos', () => {
        const s = src('components/landing/PublicLanding.tsx');
        expect(s).toContain('text-xs font-semibold uppercase leading-5 tracking-[0.16em] text-teal-300 sm:tracking-[0.2em]');
    });
});
