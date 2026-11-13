/**
 * Genera data-engine/app/data/ir_live_links.json a partir de lib/ir-registry.ts.
 *
 * El registro IR vive en el frontend y es la UNICA fuente (verificacion manual,
 * fecha exacta o nada). El backend solo necesita un dato: el enlace oficial al
 * directo del evento (kind 'directo'; si no hay, 'webcast') para incluirlo en el
 * aviso "hoy presenta resultados". Este script lo extrae y el guard
 * scripts/ir-live-links-guard.test.ts hace fallar la suite si el JSON se queda
 * atras respecto al registro.
 *
 * Uso: npm run sync:ir-live-links
 */
import { writeFileSync } from 'node:fs';

// @ts-expect-error TS5097: node --experimental-strip-types exige la extension explicita.
import { IR_REGISTRY } from '../lib/ir-registry.ts';

/** { TICKER: { 'AAAA-MM-DD': { kind, url, source } } } con claves ordenadas (diff estable). */
export function extractLiveLinks(registry) {
    const out = {};
    for (const ticker of Object.keys(registry).sort()) {
        const events = {};
        for (const event of registry[ticker].events) {
            const assets = event.assets ?? [];
            const live = assets.find((a) => a.kind === 'directo') ?? assets.find((a) => a.kind === 'webcast');
            if (live) events[event.date] = { kind: live.kind, url: live.url, source: live.source };
        }
        if (Object.keys(events).length > 0) out[ticker] = events;
    }
    return out;
}

const isMain = process.argv[1] && import.meta.url.endsWith(process.argv[1].split('/').pop());
if (isMain) {
    const json = `${JSON.stringify(extractLiveLinks(IR_REGISTRY), null, 2)}\n`;
    writeFileSync('data-engine/app/data/ir_live_links.json', json);
    console.log(`ir_live_links.json: ${Object.keys(extractLiveLinks(IR_REGISTRY)).length} emisores con directo verificado`);
}
