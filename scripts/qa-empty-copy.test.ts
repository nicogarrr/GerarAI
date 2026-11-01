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
 // Las cadenas visibles viven en los diccionarios i18n (carril C); los
 // componentes las referencian por clave. El guard verifica ambos extremos.
 const esPlan = JSON.parse(read('lib/i18n/messages/es/plan.json'));
 const esExport = JSON.parse(read('lib/i18n/messages/es/export.json'));
 assert.ok(!read('app/(root)/plan/page.tsx').includes('>Planificación<'));
 assert.ok(!read('components/plan/PlanView.tsx').includes('Análisis de Drift') && !JSON.stringify(esPlan).includes('Análisis de Drift'));
 assert.ok(read('components/plan/PlanView.tsx').includes('plan.sections.goalTitle'));
 assert.equal(esPlan.sections.goalTitle, 'Objetivo y asignación');
 assert.ok(read('components/export/ExportView.tsx').includes('export.journal.exportCta'));
 assert.equal(esExport.journal.exportCta, 'Exportar diario');
 assert.ok(read('components/export/ObsidianVaultCard.tsx').includes('export.obsidian.cta'));
 assert.equal(esExport.obsidian.cta, 'Descargar para Obsidian (.zip)');
});
