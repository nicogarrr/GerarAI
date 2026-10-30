import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
test('plan formats amounts only with declared base currency and hides technical id',()=>{
 const s=readFileSync('components/plan/PlanView.tsx','utf8');
 assert.match(s,/typeof record.base_currency === 'string'/);
 // «Divisa base» es visible en la ficha del plan (decisión de auditoría); solo se oculta el id técnico.
 assert.match(s,/hiddenKeys=\{\['id'[,\]]/);
 assert.match(s,/target_pct: 'Peso objetivo'/);
 assert.match(s,/band_pct: 'Banda de tolerancia'/);
});
test('alert removal requires confirmation before mutation and names its rule',()=>{
 const s=readFileSync('components/alerts/AlertsManager.tsx','utf8');
 assert.match(s,/onClick=\{\(\) => setConfirmAlert\(alert\)\}/,'el botón de borrado abre la confirmación, no muta');
 assert.match(s,/onConfirm=\{\(\) => \{ if \(confirmAlert\) handleDeleteAlert\(confirmAlert\._id\); \}\}/,'la mutación solo corre al confirmar');
 const block=s.slice(s.indexOf('const handleDeleteAlert'),s.indexOf('const getAlertLabel'));
 assert.ok(!block.includes('window.confirm'),'la confirmación vive en ConfirmDialog, no en window.confirm');
 assert.match(s,/Eliminar alerta: \$\{getAlertLabel\(alert\)\}/);
});
test('screeners pluralize counts; ProPicks uses Spanish score labels',()=>{
 const s=readFileSync('app/(root)/screeners/page.tsx','utf8');
 assert.match(s,/result.match_count === 1 \? 'coincidencia' : 'coincidencias'/);
 const p=readFileSync('components/proPicks/EnhancedProPicksFilters.tsx','utf8');
 assert.doesNotMatch(p,/Score Mínimo|Score General/);
});
test('plan formats nested money, all weights, details and date',()=>{
 const s=readFileSync('components/plan/PlanView.tsx','utf8');
 for(const fragment of ["direction: 'Operación'", "detail: 'Detalle'", "within_band: 'Dentro de la banda'", "key === 'amount_base'", "key === 'current_weights'", 'formatMarketDate(value as string)', 'whitespace']) {
  if(fragment==='whitespace') continue;
  assert.ok(s.includes(fragment),fragment);
 }
 assert.match(readFileSync('components/data/RecordViews.tsx','utf8'),/whitespace-pre-line/);
});
