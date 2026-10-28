import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
const source=readFileSync('components/brain/GlobalBrain.tsx','utf8') + '\n' + readFileSync('components/brain/GlobalBrainPanel.tsx','utf8');
test('mobile brain clears BottomNav and uses full flat icon without shell',()=>{
 assert.ok(source.includes('bottom-[calc(7rem+env(safe-area-inset-bottom))]'));
 assert.ok(source.includes('shadow-none bg-transparent hover:bg-transparent'));
 assert.ok(!source.split('// Burbuja fija:')[1].split('// Panel:')[0].includes('bg-indigo-600'));
 assert.ok(source.includes('h-14 w-14 p-0'));
 assert.ok(source.includes('h-14 w-14 shrink-0 object-contain'));
 assert.ok(!source.split('// Burbuja fija:')[1].split('// Panel:')[0].includes('bg-white'));
});
test('panel header shows the flat logo with no white disk',()=>{
 assert.ok(!source.includes('rounded-full bg-white'));
 assert.ok(source.includes('<BrainGlassesIcon className="h-9 w-9 shrink-0 object-contain" />'));
});
