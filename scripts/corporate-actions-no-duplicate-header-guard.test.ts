import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const view = readFileSync('components/corporate-actions/CorporateActionsView.tsx', 'utf8');
const list = readFileSync('components/data/RecordViews.tsx', 'utf8');

test('la tarjeta de acciones corporativas no repite el encabezado de la página', () => {
    assert.match(view, /<RecordList[\s\S]*?\bhideTitle\b/);
    assert.doesNotMatch(view, /description="Dividendos, splits/);
});

test('RecordList con hideTitle conserva el título como texto accesible', () => {
    assert.match(list, /hideTitle \? \(\s*<CardTitle[^>]*className="sr-only">\{title\}<\/CardTitle>/);
});
