import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
// Los textos de Pro Picks viven en el diccionario es (i18n): se comprueban junto al código.
const ES_PROPICKS_JSON = readFileSync('lib/i18n/messages/es/propicks.json', 'utf8');
const read=(path:string)=>readFileSync(path,'utf8');
test('Descubrir: se retira telemetría sin quitar avisos de calidad',()=>{
 assert.ok(!read('app/(root)/insider/page.tsx').includes('Metodología · Monitor'));
 const signals=read('components/insider/InsiderSignalsView.tsx');
 assert.ok(!signals.includes('Monitor cada 15 min'));
 for(const code of ['durable.header','durable.detail','degradedCopy','persistedSourceCopy','loadMoreInsiderFilings'])assert.ok(signals.includes(code));
 assert.ok(!(read('app/(root)/propicks/page.tsx') + ES_PROPICKS_JSON).includes('Selección vigente del último run'));
 assert.ok((read('app/(root)/propicks/page.tsx') + ES_PROPICKS_JSON).includes('no como validación de la estrategia'));
 assert.ok(read('app/(root)/ownership/page.tsx').includes('ownershipLimitations(item)'), 'los límites siguen en el desplegable final de #1937');
 assert.ok(!read('app/(root)/ownership/page.tsx').includes('tabla revisada en código'));
});
