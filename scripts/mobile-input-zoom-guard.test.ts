import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, it } from 'node:test';

// Zoom automático de iOS: al enfocar un input/select/textarea con font-size
// menor de 16px, Safari hace zoom de página y desmonta el layout a 390px.
// Convención: `text-base` en móvil y `sm:text-sm`/`sm:text-xs` en desktop.

const FIXED = [
    ['app/(root)/research/sources/page.tsx', 'px-3 text-base text-gray-200 sm:text-sm', 5],
    ['components/portfolio/PortfolioTransactions.tsx', 'px-2 text-base text-gray-100 sm:text-sm', 2],
    ['components/research/FundamentalModelPanels.tsx', 'text-base text-gray-200 sm:h-10 sm:text-sm', 2],
    ['app/(root)/screeners/page.tsx', 'font-mono text-base sm:text-xs', 1],
    ['app/(root)/screeners/page.tsx', 'px-3 text-base text-gray-200 sm:text-sm', 1],
    ['components/screeners/FilterFields.tsx', 'px-3 text-base text-gray-200 sm:text-sm', 1],
] as const;

function* walk(dir: string): Generator<string> {
    for (const entry of readdirSync(dir)) {
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) yield* walk(full);
        else if (full.endsWith('.tsx')) yield full;
    }
}

describe('guard móvil: inputs sin zoom automático de iOS (text-base en móvil)', () => {
    it('los controles corregidos llevan text-base con réplica sm:', () => {
        for (const [file, needle, count] of FIXED) {
            const src = readFileSync(file, 'utf8');
            const n = src.split(needle).length - 1;
            assert.equal(n, count, `${file} debe tener ${count} controles con "${needle}"`);
        }
    });
    it('ningún control de app/ o components/ queda con text-sm/xs sin text-base', () => {
        // El salto hasta className atraviesa handlers inline (`onChange={(e) => ...}`):
        // `[^>]` moría en el `>` del arrow y esos controles quedaban fuera del
        // escaneo (falso negativo: 9 controles con text-sm en main).
        const re = /<(?:input|textarea|select)(?:(?:[^>{]|\{(?:[^{}]|\{[^{}]*\})*\}){0,600}?)className="([^"]*)"/g;
        const offenders: string[] = [];
        for (const root of ['app', 'components']) {
            for (const file of walk(root)) {
                const src = readFileSync(file, 'utf8');
                for (const m of src.matchAll(re)) {
                    const c = m[1];
                    if (/\btext-(sm|xs)\b/.test(c) && !c.includes('text-base') && !c.includes('sr-only')) {
                        offenders.push(`${file}: ${c.slice(0, 80)}`);
                    }
                }
            }
        }
        assert.deepEqual(offenders, [], 'controles con font <16px en móvil (zoom iOS)');
    });
});
