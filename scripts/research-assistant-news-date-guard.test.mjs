import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
const ui = readFileSync('components/research/GuideContextPanel.tsx', 'utf8');
test('fecha de noticias legible sin hacer pasar detección por publicación', () => {
    assert.match(ui, /news\.date_source === 'gdelt_first_seen' \? t\('research\.guideContext\.detected'\)/);
    assert.match(ui, /news\.date_source === 'ingested_at_fallback' \? t\('research\.guideContext\.ingested'\)/);
    assert.match(ui, /news\.date_source === 'source' \? t\('research\.guideContext\.published'\) : t\('research\.guideContext\.recorded'\)/);
    const guideEs = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).guideContext;
    assert.deepEqual([guideEs.detected, guideEs.ingested, guideEs.published, guideEs.recorded], ['Detectada', 'Incorporada', 'Publicada', 'Fecha registrada']);
    assert.match(ui, /news\.date \? formatUserDateTime\(news\.date\) : t\('signals\.noDate'\)/);
    assert.doesNotMatch(ui, /Origen de fecha: \{news\.date_source/);
});
