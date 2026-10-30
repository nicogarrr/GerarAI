import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
const read = (p: string) => readFileSync(p, 'utf8');
test('ProPicks never calls an empty selection Top 0 and uses the real refresh action', () => {
 const src = read('components/proPicks/EnhancedProPicksContent.tsx');
 assert.ok(src.includes("picks.length > 0 ? `Top ${formatNumber(picks.length"));
 assert.ok(src.includes(": 'Sin selección'"));
 assert.ok(src.includes('Pulsa «Generar selección ahora»'));
 // #1406: el botón anuncia su estado (etiqueta que cambia con loading).
 assert.ok(src.includes("{loading ? 'Actualizando selección...' : 'Actualizar selección'}"));
 assert.ok(src.includes("{emptyStateNeedsRun ? (loading ? 'Generando selección...' : 'Generar selección ahora') : (loading ? 'Actualizando selección...' : 'Actualizar selección')}"));
});
test('plan and export avoid repeated page names and English labels', () => {
 assert.ok(!read('app/(root)/plan/page.tsx').includes('>Planificación<'));
 assert.ok(!read('components/plan/PlanView.tsx').includes('Análisis de Drift'));
 assert.ok(read('components/plan/PlanView.tsx').includes('Objetivo y asignación'));
 assert.ok(read('components/export/ExportView.tsx').includes('Exportar diario'));
 assert.ok(read('components/export/ObsidianVaultCard.tsx').includes('Descargar para Obsidian (.zip)'));
});
