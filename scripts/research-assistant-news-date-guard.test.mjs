import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
const ui = readFileSync('components/research/GuideContextPanel.tsx', 'utf8');
test('fecha de noticias legible sin hacer pasar detección por publicación', () => {
    assert.match(ui, /news\.date_source === 'gdelt_first_seen' \? 'Detectada'/);
    assert.match(ui, /news\.date_source === 'ingested_at_fallback' \? 'Incorporada'/);
    assert.match(ui, /news\.date_source === 'source' \? 'Publicada' : 'Fecha registrada'/);
    assert.match(ui, /news\.date \? formatUserDateTime\(news\.date\) : t\('signals\.noDate'\)/);
    assert.doesNotMatch(ui, /Origen de fecha: \{news\.date_source/);
});
