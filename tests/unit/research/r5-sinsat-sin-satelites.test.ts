import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { MODULES } from '@/lib/research/research-views';

// Nico (12-nov): «Quita esa funcion no aporta». La función de satélites/órbitas
// era solo de ASTS (`ticker === 'ASTS'` en la ficha). ASTS sigue siendo una
// empresa normal: solo desaparece lo orbital.
const read = (path: string) => readFileSync(path, 'utf8');

describe('r5-sinsat: fuera la función de satélites/órbitas de ASTS', () => {
    it('la ficha ya no tiene ningún caso fijado para ASTS', () => {
        const page = read('app/(root)/research/[ticker]/page.tsx');
        expect(page).not.toMatch(/ticker\s*===\s*'ASTS'/);
        expect(page).not.toMatch(/AstOrbitPanel|asts-orbits|buildSatellitesSection|fichaSecSatelites|fichaSatellitesPanel/);
    });

    it('no queda el módulo «satellites» en Seguimiento', () => {
        expect(MODULES.map((module) => module.key)).not.toContain('satellites');
    });

    it('se borran el panel, el gráfico, las acciones y sus textos', () => {
        for (const file of [
            'components/research/AstOrbitPanel.tsx',
            'components/research/AstSmaChart.tsx',
            'lib/actions/asts-orbits.actions.ts',
            'lib/research/ast-catalog-text.ts',
        ]) expect(existsSync(file), file).toBe(false);
    });

    it('ninguna llamada ni tipo generado apunta a /api/market/asts', () => {
        expect(read('lib/research/openapi.generated.ts')).not.toContain('/api/market/asts');
    });

    it('sin claves de traducción orbitales en es ni en en', () => {
        for (const locale of ['es', 'en']) {
            const research = JSON.parse(read(`lib/i18n/messages/${locale}/research.json`));
            const landing = JSON.parse(read(`lib/i18n/messages/${locale}/landing.json`));
            expect(research.astOrbit, locale).toBeUndefined();
            for (const key of ['fichaSecSatelites', 'fichaSatellitesPanel', 'fichaOrbitalSignal', 'fichaOrbitalOnlyAsts']) {
                expect(research[key], `${locale}.${key}`).toBeUndefined();
            }
            expect(landing.metodologia?.orbital, locale).toBeUndefined();
            expect(JSON.stringify(landing), locale).not.toContain('CelesTrak');
        }
    });
});
