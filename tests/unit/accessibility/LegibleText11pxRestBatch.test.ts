import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

// Lote resto del suelo de lectura (12 px, auditoría 11-nov): etiquetas
// informativas a 11 px fuera de research/company — «sin valor justo» y
// etiqueta de valor justo del resumen personalizado, nota de la tarjeta
// de precio objetivo, nota de fees en transacciones, título «Ganancia» del
// resumen de cartera, badge de señal en posiciones y badge «macro» del
// calendario. Ninguno es marcador tipográfico: todo es lectura.

const FILES = [
    'components/PersonalizedOverview.tsx',
    'components/portfolio/PortfolioTransactions.tsx',
    'components/portfolio/PortfolioSummary.tsx',
    'components/portfolio/HoldingSignals.tsx',
    'components/calendar/MacroEventRow.tsx',
];

const src = (p: string) => readFileSync(p, 'utf8');

describe('texto legible lote resto: nada de lectura bajo 12 px', () => {
    it.each(FILES)('%s no tiene texto a 11 px ni 10 px', (path) => {
        const s = src(path);
        expect(s.match(/text-\[11px\]/g) ?? [], 'queda text-[11px]').toHaveLength(0);
        expect(s.match(/text-\[10px\]/g) ?? [], 'queda text-[10px]').toHaveLength(0);
    });

    it('el título «Ganancia» del resumen va a 12 px fijos, sin duplicar sm:', () => {
        const s = src('components/portfolio/PortfolioSummary.tsx');
        // P23 v2 (18-nov): la excepción tracking-normal móvil desaparece; la
        // etiqueta queda idéntica a sus hermanas y la tarjeta pasa a 1
        // columna <420px (a 12px el token irrompible se recortaba en 2).
        expect(s).toContain('text-gray-400 text-xs uppercase tracking-wider font-semibold mb-1');
        expect(s).not.toContain('tracking-normal sm:tracking-wider');
        expect(s).not.toContain('sm:text-xs');
    });

    it('la etiqueta de valor justo del resumen personalizado va a 12 px', () => {
        const s = src('components/PersonalizedOverview.tsx');
        expect(s).toContain('whitespace-nowrap text-xs text-gray-400');
    });

    it('el badge «macro» del calendario va a 12 px conservando su caja', () => {
        const s = src('components/calendar/MacroEventRow.tsx');
        expect(s).toContain('rounded border border-teal-400/30 px-1.5 py-0.5 text-xs font-semibold uppercase text-teal-300');
    });
});
