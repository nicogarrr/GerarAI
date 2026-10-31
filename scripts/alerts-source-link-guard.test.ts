/**
 * Guarda F172: una alerta disparada por un filing/noticia/Form 4 debe ofrecer
 * enlace directo al documento fuente. Antes todas las tarjetas solo llevaban
 * a /research/[ticker] y el filing era inalcanzable desde /alerts.
 * La API resuelve source_url desde metadata.source_url (insider) o el
 * NewsEvent enlazado; sin URL conocida la UI no inventa enlace.
 *
 * Ejecución: node --experimental-strip-types --test scripts/alerts-source-link-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const readSource = (rel: string) => readFileSync(join(root, rel), 'utf8');

describe('alerts source link guard (F172)', () => {
    it('la API tipa source_url y la acción lo mapea sin inventarlo', () => {
        const actions = readSource('lib/actions/alerts.actions.ts');
        assert.ok(actions.includes('source_url: string | null'), 'ResearchAlertRow tipa source_url nullable');
        assert.ok(actions.includes('sourceUrl: row.source_url ?? null'), 'sin URL se propaga null, nunca una inventada');
    });

    it('la tarjeta enlaza al documento fuente en pestaña nueva solo cuando existe', () => {
        const src = readSource('components/alerts/AlertsManager.tsx');
        assert.ok(src.includes('href={item.sourceUrl}'), 'enlace directo al documento fuente');
        // i18n: la etiqueta «Abrir documento» vive en messages/<locale>/alerts.json (triggered.openDocument).
        assert.ok(src.includes("ti('alerts.triggered.openDocument')"), 'etiqueta del enlace al documento');
        assert.ok(src.includes('target="_blank"'), 'documento externo en pestaña nueva');
        assert.ok(src.includes('item.sourceUrl &&'), 'el enlace solo se muestra con URL conocida');
        assert.ok(
            src.includes("href={alertThesisHref(item.ticker)}"),
            'el enlace a la investigación se conserva',
        );
    });
});
