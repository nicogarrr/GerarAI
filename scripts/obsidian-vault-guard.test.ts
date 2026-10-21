/**
 * Guarda del vault Obsidian: la descarga pasa por el proxy same-origin (la
 * firma Research OS nunca llega al navegador), la UI apunta a ese proxy y la
 * respuesta es privada y no cacheable (datos del tenant).
 * Ejecución: node --experimental-strip-types --test scripts/obsidian-vault-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const source = (relativePath: string): string => readFileSync(join(root, relativePath), 'utf8');

describe('vault Obsidian detrás del proxy same-origin', () => {
    const proxyPath = join('app', 'api', 'obsidian', 'vault.zip', 'route.ts');

    it('el proxy existe y exige sesión antes de firmar', () => {
        assert.ok(existsSync(join(root, proxyPath)), 'debe existir el proxy /api/obsidian/vault.zip');
        const proxy = source(proxyPath);
        assert.match(proxy, /await requireAuthenticatedUser\(\)/);
        assert.match(proxy, /researchIdentityHeaders\(\{ method: 'GET', path \}\)/);
    });

    it('el proxy fija la ruta backend como constante (sin SSRF por cliente)', () => {
        const proxy = source(proxyPath);
        assert.match(proxy, /const path = '\/api\/obsidian\/vault\.zip'/);
        assert.doesNotMatch(proxy, /fetch\(\s*`/);
    });

    it('la respuesta es privada, no cacheable y con nosniff', () => {
        const proxy = source(proxyPath);
        assert.match(proxy, /private, no-store/);
        assert.match(proxy, /'x-content-type-options': 'nosniff'/);
        assert.match(proxy, /gerarai-obsidian-vault\.zip/);
    });

    it('la UI enlaza al proxy y nunca al backend directo', () => {
        const card = source(join('components', 'export', 'ObsidianVaultCard.tsx'));
        assert.match(card, /href="\/api\/obsidian\/vault\.zip"/);
        assert.doesNotMatch(card, /FMP_BACKEND_URL/);
        const page = source(join('app', '(root)', 'export', 'page.tsx'));
        assert.match(page, /<ObsidianVaultCard \/>/);
    });

    it('la descarga confirma, no navega fuera en error y lo dice inline', () => {
        const card = source(join('components', 'export', 'ObsidianVaultCard.tsx'));
        assert.match(card, /<ConfirmDialog/, 'la descarga pide confirmación con el diálogo compartido');
        assert.match(card, /onConfirm=\{handleDownload\}/, 'la descarga solo corre al confirmar');
        assert.match(card, /response\.ok/, 'un HTTP no-OK se trata como error');
        assert.doesNotMatch(card, /location\.assign|window\.confirm/, 'ni navegación a un JSON de error ni confirm nativo');
        assert.match(card, /role="alert"/, 'el fallo de descarga se muestra inline');
    });

    it('la ruta backend del vault existe en el data-engine', () => {
        const route = source(join('data-engine', 'app', 'api', 'routes', 'obsidian.py'));
        assert.match(route, /@vault_router\.get\("\/vault\.zip"\)/);
        const router = source(join('data-engine', 'app', 'api', 'router.py'));
        assert.match(router, /obsidian\.vault_router, prefix="\/obsidian"/);
    });
});
