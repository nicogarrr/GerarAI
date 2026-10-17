/**
 * Guard: el canonico lo declara cada pagina publica, nunca el layout raiz.
 *
 * `app/layout.tsx` tenia `alternates.canonical: '/'`: en Next.js el canonico
 * del layout raiz lo heredan TODAS las rutas que no declaran el suyo, asi que
 * /metodologia y /help (index: true) se presentaban al indice como copias de
 * la landing. Cada pagina publica indexable declara ahora su canonico.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/canonical-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const rootLayout = readFileSync('app/layout.tsx', 'utf8');
const landing = readFileSync('components/landing/PublicLanding.tsx', 'utf8');
const metodologia = readFileSync('app/(public)/metodologia/page.tsx', 'utf8');
const help = readFileSync('app/(public)/help/page.tsx', 'utf8');

describe('canonico por ruta', () => {
    it('el layout raiz NO declara canonico (lo heredarian todas las rutas)', () => {
        assert.ok(!/alternates\s*:\s*\{[^}]*canonical/.test(rootLayout), 'app/layout.tsx no debe declarar alternates.canonical');
    });
    it('cada pagina publica indexable declara su canonico', () => {
        assert.match(landing, /alternates:\s*\{\s*canonical:\s*'\/'\s*\}/);
        assert.match(metodologia, /alternates:\s*\{\s*canonical:\s*'\/metodologia'\s*\}/);
        assert.match(help, /alternates:\s*\{\s*canonical:\s*'\/help'\s*\}/);
    });
});
