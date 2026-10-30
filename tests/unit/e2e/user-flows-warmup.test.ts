import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { isRetryableWarmup, WARMUP_ROUTES } from '@/e2e/user-flows/warmup-routes';

const dir = path.join(process.cwd(), 'e2e/user-flows');

function routesVisitedBySpecs(): string[] {
    const routes = new Set<string>();
    for (const file of readdirSync(dir).filter((f) => f.endsWith('.spec.ts'))) {
        const src = readFileSync(path.join(dir, file), 'utf8');
        for (const m of src.matchAll(/visit\(page,\s*["'`]([^"'`]+)["'`]/g)) {
            routes.add(m[1].split(/[?#]/)[0]);
        }
    }
    return [...routes].sort();
}

describe('calentamiento de la suite de flujos de usuario', () => {
    it('compila todas las rutas que visitan los specs (salvo /sign-in, que ya calienta el webServer)', () => {
        // `/research/${TICKER}` cuenta como cualquier segmento en esa posición.
        const covered = (route: string) => {
            const re = new RegExp(`^${route.replace(/[.*+?^()|[\]\\]/g, '\\$&').replace(/\$\{[^}]+\}/g, '[^/]+')}$`);
            return WARMUP_ROUTES.some((w) => re.test(w));
        };
        const missing = routesVisitedBySpecs().filter((r) => r !== '/sign-in' && !covered(r));
        expect(missing).toEqual([]);
    });

    it('reintenta solo lo que es del servidor de desarrollo, no las respuestas válidas', () => {
        expect(isRetryableWarmup(500, null)).toBe(true);
        expect(isRetryableWarmup(null, null)).toBe(true);
        expect(isRetryableWarmup(null, 'page.goto: net::ERR_ABORTED at http://x/portfolio')).toBe(true);
        expect(isRetryableWarmup(null, 'net::ERR_CONNECTION_RESET')).toBe(true);
        expect(isRetryableWarmup(200, null)).toBe(false);
        // La 404 de una ruta inexistente es la respuesta esperada, no un fallo.
        expect(isRetryableWarmup(404, null)).toBe(false);
        expect(isRetryableWarmup(null, 'net::ERR_NAME_NOT_RESOLVED')).toBe(false);
    });

    it('playwright.config solo engancha el calentamiento en la suite de flujos', () => {
        const cfg = readFileSync(path.join(process.cwd(), 'playwright.config.ts'), 'utf8');
        expect(cfg).toMatch(/runUserFlows = runUiE2E && process\.env\.E2E_USER_FLOWS === "1"/);
        expect(cfg).toMatch(/globalSetup: runUserFlows \? "\.\/e2e\/user-flows\/global-setup\.ts" : undefined/);
    });
});
