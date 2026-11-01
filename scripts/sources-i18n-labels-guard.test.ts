import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('app/(root)/research/sources/page.tsx', 'utf8');
// Los tiers viven en el catálogo compartido (lo usa también la búsqueda
// universal); los tipos de documento siguen curados en la página porque los
// selects de subida solo ofrecen tipos elegibles por el usuario.
const display = readFileSync('lib/research/source-display.ts', 'utf8');

// Catálogo del backend: tipos de documento (ingesta SEC/ESEF/CNMV, subidas,
// URLs, seeds, FMP, transcripts) y tiers de source_hierarchy_service.py.
const BACKEND_SOURCE_TYPES = [
    'sec', 'esef', 'cnmv', 'url', 'manual_upload', 'upload', 'manual',
    'seed', 'fmp', 'fmp_profile', 'manual_transcript', 'filing',
    'company_ir', 'transcript',
];
const BACKEND_TIERS = [
    'tier_1_regulatory', 'tier_2_company', 'tier_3_transcript',
    'tier_4_reputable_media', 'tier_5_data_provider', 'tier_6_bootstrap',
    'tier_7_user_input', 'tier_unknown', 'primary', 'secondary',
];

test('F323: tipo y nivel de fuente se pintan con etiqueta en espanol', () => {
    assert.match(page, /\{sourceTypeLabel\(document\.source_type(, locale === 'en' \? t : undefined)?\)\}/);
    assert.match(page, /\{sourceTierLabel\(document\.source_tier\)\}/);
    assert.doesNotMatch(page, /\{document\.source_type\}<\/td>/);
    assert.doesNotMatch(page, /\{document\.source_tier\}<\/td>/);
});

test('F323: los mapas cubren el catalogo del backend', () => {
    for (const key of BACKEND_SOURCE_TYPES) {
        assert.match(page, new RegExp(`${key}: '`), `falta source_type ${key}`);
    }
    for (const key of BACKEND_TIERS) {
        assert.match(display, new RegExp(`${key}: '`), `falta tier ${key}`);
    }
    assert.match(page, /SOURCE_TYPE_LABELS\[value\] \?\? sourceDisplay\(value\)/);
    assert.match(page, /sourceTierDisplay\(value\)/);
    assert.match(display, /SOURCE_TIER_LABELS\[value\] : value\.replaceAll/);
});
