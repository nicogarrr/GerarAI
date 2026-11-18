import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

// Etiquetas de estado/datos DCA bajo el suelo de lectura de 12 px (auditoría
// móvil 18-nov-2026, prod 390x844): chips «watchlist»/«En cartera» medidos a
// 10 px en /watchlist; la nota ámbar de dato antiguo del badge DCA, las
// etiquetas de horizonte/casos de la tarjeta de aciertos y el volumen de
// MoversTable estaban a 10 px en código (veracidad: cuántos casos hay detrás
// de un %). El suelo del producto es text-xs desde el 11-nov
// (readable-grey-text-contrast).

const src = (p: string) => readFileSync(p, 'utf8');

describe('etiquetas de estado DCA a 12 px (text-xs), no 10 px', () => {
    it('la nota de dato antiguo del badge DCA', () => {
        const s = src('components/watchlist/DcaLevelBadge.tsx');
        expect(s).toContain('className="text-xs leading-tight text-amber-400 whitespace-nowrap"');
    });

    it('los chips de pertenencia (watchlist / en cartera)', () => {
        const s = src('components/watchlist/DcaAlertSettingsList.tsx');
        expect(s).toContain('px-1.5 text-xs text-gray-300');
        expect(s).toContain('px-1.5 text-xs text-teal-300');
        expect(s).not.toContain('text-[10px]');
    });

    it('horizonte y nº de casos de la tarjeta de aciertos', () => {
        const s = src('components/watchlist/DcaHitRatesCard.tsx');
        expect(s).toContain('className="block text-xs font-medium text-gray-500 sm:hidden"');
        expect(s).toContain('className="block text-xs text-gray-500"');
        expect(s).not.toContain('text-[10px]');
    });

    it('el volumen móvil de MoversTable', () => {
        const s = src('components/market/MoversTable.tsx');
        expect(s).toContain('className="mt-1 text-xs text-gray-500 sm:hidden"');
        expect(s).not.toContain('text-[10px]');
    });
});
