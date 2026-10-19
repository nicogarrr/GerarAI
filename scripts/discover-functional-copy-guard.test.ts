import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const read=(path:string)=>readFileSync(path,'utf8');
test('Descubrir: se retira telemetría sin quitar avisos de calidad',()=>{
 assert.ok(!read('app/(root)/insider/page.tsx').includes('Metodología · Monitor'));
 const signals=read('components/insider/InsiderSignalsView.tsx');
 assert.ok(!signals.includes('Monitor cada 15 min'));
 for(const code of ['durable.header','durable.detail','degradedCopy','persistedSourceCopy','loadMoreInsiderFilings'])assert.ok(signals.includes(code));
 assert.ok(!read('app/(root)/propicks/page.tsx').includes('Selección vigente del último run'));
 assert.ok(read('app/(root)/propicks/page.tsx').includes('no como validación de la estrategia'));
 assert.ok(read('app/(root)/ownership/page.tsx').includes('ownershipLimitations(item)'), 'los límites siguen en el desplegable final de #1937');
 assert.ok(!read('app/(root)/ownership/page.tsx').includes('tabla revisada en código'));
});
