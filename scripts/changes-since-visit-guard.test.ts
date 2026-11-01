/**
 * Guard del banner «Desde tu última visita» (QA ASTS 21-oct-2026): la misma
 * noticia en dos idiomas creaba dos cambios de tesis duplicados. El backend
 * los agrupa por identidad atribuida (puente ResearchReview -> NewsEvent) y
 * el banner mantiene revisables la fuente y las URLs absorbidas.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const banner = readFileSync('components/research/ChangesSinceVisit.tsx', 'utf8');
const service = readFileSync('data-engine/app/services/company_changes_service.py', 'utf8');

test('el banner proyecta la fuente del evento y las fuentes absorbidas (sin pintar etiquetas, #3527)', () => {
    assert.ok(banner.includes('fuente_url'), 'proyecta fuente_url');
    assert.ok(banner.includes('tambien_en'), 'proyecta tambien_en');
    assert.match(banner, /target="_blank" rel="noopener noreferrer"/, 'enlaces externos seguros');
});

test('el backend agrupa solo por identidad atribuida vía ResearchReview -> NewsEvent', () => {
    assert.ok(service.includes('ResearchReview.thesis_change_id.in_'), 'puente por review');
    assert.ok(service.includes('display_translation'), 'usa la traducción atribuida cacheada');
    assert.ok(service.includes('group_change_items'), 'agrupa con la regla compartida');
    assert.ok(!service.includes('SequenceMatcher'), 'sin similitud difusa');
});

test('la tarjeta «Últimos cambios» (snapshot) agrupa con el mismo lote sin N+1', () => {
    const snapshot = readFileSync('data-engine/app/services/company_snapshot_service.py', 'utf8');
    assert.ok(snapshot.includes('_enrich_changes_many'), 'enriquecimiento compartido');
    assert.ok(snapshot.includes('ResearchReview.thesis_change_id.in_'), 'una query de reviews para todo el lote');
    assert.ok(snapshot.includes('NewsEvent.id.in_(event_ids)'), 'una query de eventos para todo el lote');
});
