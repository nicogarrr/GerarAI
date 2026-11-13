/**
 * ir_live_links.json (backend) nunca se queda atras del registro IR (frontend).
 * El JSON lo genera scripts/sync-ir-live-links.mjs; si este guard falla, corre
 * `npm run sync:ir-live-links` y comitea el JSON regenerado.
 * Ejecucion: node --experimental-strip-types --test scripts/ir-live-links-guard.test.ts
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { IR_REGISTRY } from '../lib/ir-registry.ts';
import { extractLiveLinks } from './sync-ir-live-links.mjs';

test('ir_live_links.json coincide con el registro IR (directo/webcast por evento)', () => {
    const onDisk = JSON.parse(readFileSync('data-engine/app/data/ir_live_links.json', 'utf8'));
    assert.deepEqual(onDisk, extractLiveLinks(IR_REGISTRY), 'JSON desactualizado: corre npm run sync:ir-live-links');
});

test('solo enlaces https de tipo directo/webcast con su fuente', () => {
    for (const events of Object.values(extractLiveLinks(IR_REGISTRY))) {
        for (const link of Object.values(events as Record<string, { kind: string; url: string; source: string }>)) {
            assert.ok(['directo', 'webcast'].includes(link.kind));
            assert.match(link.url, /^https:\/\//);
            assert.match(link.source, /^https:\/\//);
        }
    }
});
