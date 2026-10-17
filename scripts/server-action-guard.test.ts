/**
 * Guardas de la capa de server actions: lo que un cliente puede invocar por
 * HTTP y lo que los errores devuelven al navegador.
 * Ejecución: node --experimental-strip-types --test scripts/server-action-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');

function walk(dir: string, out: string[] = []): string[] {
    for (const entry of readdirSync(dir)) {
        if (entry === 'node_modules' || entry === '.next') continue;
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) walk(full, out);
        else if (/\.tsx?$/.test(entry)) out.push(full);
    }
    return out;
}

const actionFiles = walk(join(root, 'lib', 'actions')).filter((f) =>
    /^['"]use server['"]/.test(readFileSync(f, 'utf8').trimStart()),
);

const rel = (f: string): string => f.slice(root.length + 1).replace(/\\/g, '/');

describe("server actions no exponen helpers con URL", () => {
    it('ningún fetchJSON/fetch genérico queda exportado desde un fichero use server', () => {
        // Exportar un helper que acepta una URL desde un 'use server' lo
        // convierte en un endpoint invocable por HTTP: SSRF contra la red
        // interna a traves del servidor de Vercel.
        const offenders: string[] = [];
        for (const file of actionFiles) {
            const src = readFileSync(file, 'utf8');
            if (/^export\s*\{[^}]*\b(fetchJSON|fetchJson|fetchUpstream)\b[^}]*\}/m.test(src)) {
                offenders.push(rel(file));
            }
        }
        assert.deepEqual(offenders, []);
    });

    it('los helpers con URL viven en módulos sin use server', () => {
        for (const name of ['lib/upstream/finnhub.ts']) {
            const src = readFileSync(join(root, name), 'utf8');
            assert.doesNotMatch(src.trimStart(), /^['"]use server['"]/, name);
        }
    });
});

describe("un 'use server' solo exporta funciones", () => {
    it('ningún enum se exporta desde un fichero use server', () => {
        // Next valida esto en action-validate.js y lanza E352. Con un enum
        // fuera del manifiesto de actions el DCE de Turbopack lo ocultaba:
        // el fallo solo aparecia al importarlo desde un componente.
        const offenders: string[] = [];
        for (const file of actionFiles) {
            const src = readFileSync(file, 'utf8');
            if (/^export\s+enum\s/m.test(src)) offenders.push(rel(file));
            if (/^export\s+const\s+\w+\s*=\s*\{/m.test(src)) offenders.push(rel(file));
        }
        assert.deepEqual(offenders, []);
    });
});

describe('los errores no filtran credenciales al cliente', () => {
    it('los mensajes de error de upstream redactan la query', () => {
        const src = readFileSync(join(root, 'lib/upstream/finnhub.ts'), 'utf8');
        assert.match(src, /redactUrl/);
        // Ningún throw debe interpolar la url cruda.
        for (const line of src.split('\n')) {
            if (!line.includes('throw new')) continue;
            assert.ok(
                !/\$\{url\}/.test(line),
                `mensaje de error con la URL sin redactar: ${line.trim()}`,
            );
        }
    });

    it('redactUrl limpia las claves de credencial conocidas', async () => {
        // @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
        const { redactUrl } = await import('../lib/upstream/redact.ts');
        // La key de Finnhub viaja en ?token=; el mensaje de error de la
        // accion la devolvia entera al navegador.
        const redacted = redactUrl('https://finnhub.io/api/v1/quote?symbol=AAPL&token=SUPERSECRET');
        assert.ok(!redacted.includes('SUPERSECRET'), redacted);
        assert.ok(redacted.includes('REDACTED'), redacted);
        assert.ok(redacted.includes('symbol=AAPL'), redacted);
        // Una URL sin credenciales se devuelve intacta.
        assert.equal(
            redactUrl('https://finnhub.io/api/v1/quote?symbol=AAPL'),
            'https://finnhub.io/api/v1/quote?symbol=AAPL',
        );
    });
});

describe('los segmentos numéricos del path se validan', () => {
    it('los ids interpolados en paths de acciones están validados', () => {
        const targets = ['lib/actions/taxes.actions.ts', 'lib/actions/thesis-jobs.actions.ts'];
        for (const name of targets) {
            const src = readFileSync(join(root, name), 'utf8');
            assert.match(src, /assert(Year|PositiveInt)\(/, name);
        }
    });
});
