/**
 * Guarda F149: la insignia de «Noticias destacadas» nunca afirma vínculo con
 * la cartera salvo que el ticker esté entre los símbolos reales del usuario.
 * `related` del proveedor = compañía mencionada en el titular, no tenencia.
 * Test SEMÁNTICO sobre el helper puro (no solo cadenas UI).
 *
 * Ejecución: node --experimental-strip-types --test scripts/news-section-distinction-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import {
    newsBadge,
// @ts-expect-error TS5097: la extensión .ts explícita la exige node --experimental-strip-types en runtime
} from '../lib/newsBadge.ts';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const src = readFileSync(join(root, 'components/NewsSection.tsx'), 'utf8');
const es = JSON.parse(readFileSync(join(root, 'lib/i18n/messages/es/home.json'), 'utf8'));
const en = JSON.parse(readFileSync(join(root, 'lib/i18n/messages/en/home.json'), 'utf8'));

describe('newsBadge (semántica F149)', () => {
    it('artículo general con related=AAPL pero SIN AAPL en cartera: mencionada, nunca holding', () => {
        // El caso del dictamen: feed general, related del proveedor presente.
        assert.deepEqual(newsBadge({ related: 'AAPL' }, undefined), { kind: 'mentioned', ticker: 'AAPL' });
        assert.deepEqual(newsBadge({ related: 'AAPL' }, []), { kind: 'mentioned', ticker: 'AAPL' });
        assert.deepEqual(newsBadge({ related: 'AAPL' }, ['MSFT', 'V']), { kind: 'mentioned', ticker: 'AAPL' });
    });

    it('related presente en los símbolos del usuario: holding (normaliza caso/espacios)', () => {
        assert.deepEqual(newsBadge({ related: 'aapl' }, [' msft ', 'AAPL']), { kind: 'holding', ticker: 'AAPL' });
    });

    it('sin related: mercado general', () => {
        assert.deepEqual(newsBadge({}, ['AAPL']), { kind: 'general' });
        assert.deepEqual(newsBadge({ related: '  ' }, ['AAPL']), { kind: 'general' });
        assert.deepEqual(newsBadge({ related: null }, undefined), { kind: 'general' });
    });
});

describe('news section UI (F149)', () => {
    it('la UI usa el helper y nunca pinta related crudo como vínculo', () => {
        assert.ok(src.includes('newsBadge(article, symbols)'), 'la insignia debe salir del helper');
        assert.ok(src.includes('Mencionada · ${ticker}'), 'mención neutral sin afirmar cartera');
        assert.ok(src.includes("t('home.news.generalMarket')"), 'etiqueta traducida para titulares sin ticker');
        assert.equal(es.news.generalMarket, 'Mercado general');
        assert.equal(en.news.generalMarket, 'General market');
        assert.ok(!src.includes('{article.related}'), 'related crudo del proveedor ya no se pinta como insignia');
    });

    it('sin frase explicativa: la propia insignia dice "Mencionada" y no sugiere posición propia', () => {
        assert.ok(!src.includes('La insignia indica'));
        assert.ok(!src.includes('La insignia con ticker'));
        assert.ok(src.includes('badge.kind === \'mentioned\''));
        assert.ok(src.includes('Mencionada · ${ticker}'));
    });
});
