import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const css = readFileSync(join(process.cwd(), 'app/globals.css'), 'utf8');
// layout.tsx importa globals.css: se lee como texto para no pasar por PostCSS.
const layout = readFileSync(join(process.cwd(), 'app/layout.tsx'), 'utf8');

describe('controles nativos en tema oscuro', () => {
    it('la raíz declara color-scheme: dark (icono de fecha, number, scroll y select legibles)', () => {
        expect(css).toMatch(/:root \{\s*color-scheme: dark;\s*\}/);
        // En la capa base, para que una utilidad [color-scheme:light] puntual siga mandando.
        const base = css.indexOf('@layer base {');
        expect(base).toBeGreaterThan(-1);
        expect(css.indexOf('color-scheme: dark;')).toBeGreaterThan(base);
    });

    it('el <meta name="color-scheme"> también dice dark', () => {
        expect(layout).toMatch(/export const viewport[\s\S]*?colorScheme: 'dark',[\s\S]*?\};/);
    });
});
