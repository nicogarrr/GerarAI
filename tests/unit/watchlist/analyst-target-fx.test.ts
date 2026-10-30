import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

// A9: la watchlist pintaba el objetivo de analistas de un ADR en USD («(ADR, USD)»)
// junto a un precio en EUR porque no pasaba los tipos de cambio de la cartera.
// Cada uso de la línea en la página debe recibirlos, como en Cartera.
describe('watchlist: objetivo de analistas con tipos de cambio de la cartera', () => {
    it('todas las AnalystTargetLine de /watchlist reciben fxRates y baseCurrency', () => {
        const source = readFileSync(path.join(process.cwd(), 'app/(root)/watchlist/page.tsx'), 'utf8');
        const uses = source.match(/<AnalystTargetLine\b[^>]*\/>/g) ?? [];
        expect(uses.length).toBeGreaterThan(0);
        for (const use of uses) {
            expect(use).toContain('fxRates={fxRates}');
            expect(use).toContain('baseCurrency={baseCurrency}');
        }
    });
});
