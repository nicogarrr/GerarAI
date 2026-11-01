// Guard: las tarjetas de alertas de Inicio no repiten la fecha del hecho si es
// la del día de entrega, solo marcan severidad alta/crítica y no ofrecen
// "Ver aviso original" en noticias (el titular ya enlaza a la fuente).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const SRC = readFileSync('components/PersonalizedOverview.tsx', 'utf8');

test('fecha del hecho omitida cuando coincide con la de entrega', () => {
    assert.ok(SRC.includes('alertHeading(copy.heading, copy.dateSuffix, item.createdAt, locale)'));
});

test('el badge de severidad solo sale en alta o crítica', () => {
    assert.ok(SRC.includes("item.severity === 'critical' || item.severity === 'high'"));
});

test('las noticias no llevan el desplegable de aviso original', () => {
    assert.ok(SRC.includes("!item.alert_type.includes('news') && <details"));
});
