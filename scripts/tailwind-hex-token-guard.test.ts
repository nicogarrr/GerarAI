/**
 * Guard de hex literales en clases Tailwind.
 *
 * Por qué: `app/globals.css` define tres superficies semanticas (`surface-0`
 * vacio/base, `surface-1` panel, `surface-2` item anidado) y su propio comentario
 * dice que sustituyen "a los hex literales que cada pagina elegia al azar". La
 * migracion nunca se aplico: 87 clases del tipo `bg-[#101010]` elegian el negro
 * a mano. En oscuro el error es invisible (#111111 esta 1/255 por encima de
 * `surface-1`), pero en un futuro modo claro dejaria decenas de superficies en
 * negro mientras `Panel`/`Stat` usan el token.
 *
 * Regla: en `app/` y `components/` no se escribe un color como `[#hex]`; se usa
 * el token (`bg-surface-1`, `text-good`, `border-gray-700`). Un hex nuevo entra
 * solo por la allowlist, con su justificacion, y desde ahi ya es codigo
 * revisable.
 *
 * NO mira `lib/`, `scripts/`, `*.css` ni atributos de SVG/recharts: ahi un hex
 * es un dato (color de serie, token de `@theme`), no una clase de estilo.
 *
 * Ejecución: node --experimental-strip-types --test scripts/tailwind-hex-token-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';

const ROOTS = ['app', 'components', 'lib'];

/** `bg-[#101010]`, `border-[#111]/50`, `text-[rgb(...)]`: utility + valor arbitrario. */
const ARBITRARY_VALUE = /(?:[\w./%#()[\],-]+)-\[([^\]]+)\]/g;
const HEX = /#[0-9a-f]{3,8}\b/i;

/**
 * Excepciones conocidas. Cada una dice que hacer con ella, no solo que existe:
 * una allowlist sin `why` es una deuda sin dueno.
 */
const ALLOWLIST: readonly { file: string; hex: string; why: string }[] = [
    {
        file: 'components/research/AstSmaChart.tsx',
        hex: '#0B1414',
        why: 'Fondo del grafico con tinte verde. No existe token equivalente (las superficies son neutras): declararlo en globals.css o aceitarlo aqui.',
    },
    {
        file: 'components/portfolio/PortfolioAllocation.tsx',
        hex: '#111111',
        why: 'Panel, 1/255 por encima de `surface-1`. Fuera de la propiedad de este cambio (PR de otro agente): migrar a `bg-surface-1`.',
    },
    {
        file: 'components/portfolio/PortfolioSummary.tsx',
        hex: '#111111',
        why: 'Panel, 1/255 por encima de `surface-1`. Fuera de la propiedad de este cambio (PR de otro agente): migrar a `bg-surface-1`.',
    },
    {
        file: 'components/portfolio/PortfolioTabs.tsx',
        hex: '#111111',
        why: 'Panel, 1/255 por encima de `surface-1`. Fuera de la propiedad de este cambio (PR de otro agente): migrar a `bg-surface-1`.',
    },
    {
        file: 'components/portfolio/PortfolioTabs.tsx',
        hex: '#0A0A0A',
        why: 'Panel, 1/255 por debajo de `surface-1`. Fuera de la propiedad de este cambio (PR de otro agente): migrar a `bg-surface-1`.',
    },
    {
        file: 'components/portfolio/PortfolioTransactions.tsx',
        hex: '#111111',
        why: 'Panel, 1/255 por encima de `surface-1`. Fuera de la propiedad de este cambio (PR de otro agente): migrar a `bg-surface-1`.',
    },
];

function sourceFiles(root: string, out: string[] = []): string[] {
    for (const entry of readdirSync(root, { withFileTypes: true })) {
        if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
        const full = path.join(root, entry.name);
        if (entry.isDirectory()) sourceFiles(full, out);
        else if (/\.(tsx|ts)$/.test(entry.name)) out.push(full);
    }
    return out;
}

type Offender = { file: string; line: number; cls: string; hex: string };

/** Todas las clases con hex literal que quedan en `app/`, `components/` y `lib/`. */
function offenders(): Offender[] {
    const found: Offender[] = [];
    for (const root of ROOTS) {
        for (const file of sourceFiles(root).sort()) {
            const lines = readFileSync(file, 'utf8').split(/\r?\n/);
            lines.forEach((line, i) => {
                for (const match of line.matchAll(ARBITRARY_VALUE)) {
                    const hex = match[1].toUpperCase().match(HEX)?.[0];
                    if (hex) {
                        found.push({
                            file: file.split(path.sep).join('/'),
                            line: i + 1,
                            cls: match[0],
                            hex,
                        });
                    }
                }
            });
        }
    }
    return found;
}

function allowed(file: string, hex: string): boolean {
    return ALLOWLIST.some((entry) => entry.file === file && entry.hex === hex);
}

describe('tailwind: los colores van por token, no por hex literal', () => {
    const found = offenders();

    it('no hay ningun hex literal fuera de la allowlist', () => {
        const sinPermiso = found.filter((entry) => !allowed(entry.file, entry.hex));

        assert.deepEqual(
            sinPermiso,
            [],
            `hex literal en clase Tailwind fuera de la allowlist:\n${sinPermiso.map((entry) => `  ${entry.file}:${entry.line} ${entry.cls}`).join('\n')}\nusa el token (bg-surface-1, text-good, border-gray-700) o anade la excepcion con su motivo`,
        );
    });

    it('la allowlist justifica cada exception', () => {
        for (const entry of ALLOWLIST) {
            assert.ok(entry.why.trim().length > 20, `${entry.file} ${entry.hex} necesita un motivo, no una excusa`);
        }
    });

    it('ninguna exception es un panel disfrazado de superficie distinta', () => {
        // #111111 y #0a0a0a son 1/255 de `surface-1`: que esten aqui significa
        // que el fichero se queda fuera del alcance, no que sean otro token.
        for (const entry of ALLOWLIST.filter((item) => ['#111111', '#0A0A0A'].includes(item.hex))) {
            assert.match(
                entry.why,
                /propiedad de este cambio/,
                `${entry.file} ${entry.hex}: si ya esta en alcance, migralo a \`bg-surface-1\` y quita la excepcion`,
            );
        }
    });

    it('los tokens de superficie que sustituyen a los hex siguen existiendo', () => {
        const css = readFileSync('app/globals.css', 'utf8');

        for (const token of ['--color-surface-0', '--color-surface-1', '--color-surface-2']) {
            assert.match(css, new RegExp(`${token}:\\s*#`), `${token} no esta definido en globals.css`);
        }
    });
});