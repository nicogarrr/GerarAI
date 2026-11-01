/**
 * F243: /research/sources mostraba auditorías «bloqueada» por falta de
 * inputs de valoración con «cobertura 100» a la vez — un 100 que sugería
 * cobertura completa. Verdad del backend (source_auditor.py): la puntuación
 * mide solo afirmaciones materiales citadas (-5 por baja confianza); el
 * bloqueo puede venir de conflictos de datos o de la traza de valoración,
 * que la puntuación NO mide. El texto debe decirlo, y el estado llamarse
 * igual en las dos páginas («bloqueada», no «fallida»).
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { auditFixLabel, auditScoreText, auditStatusLabel } from '../lib/audit-status-copy.ts';

const sourcesPage = readFileSync('app/(root)/research/sources/page.tsx', 'utf8');
const tickerPage = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const backend = readFileSync('data-engine/app/services/source_auditor.py', 'utf8');

test('bloqueada con 100/100: el texto dice que no mide el motivo del bloqueo', () => {
    const text = auditScoreText(false, 100, String);
    assert.match(text, /puntuación de respaldo de afirmaciones 100\/100 \(penaliza baja confianza y una conciliación SEC\/FMP ausente\)/);
    assert.match(text, /mide solo citas, no el motivo del bloqueo/);
});

test('superada: sin coletilla (nada que matizar)', () => {
    const text = auditScoreText(true, 92, String);
    assert.equal(text, 'puntuación de respaldo de afirmaciones 92/100 (penaliza baja confianza y una conciliación SEC/FMP ausente)');
});

test('el estado se llama «bloqueada» en ambas páginas (nunca «fallida»)', () => {
    assert.equal(auditStatusLabel(false), 'bloqueada');
    assert.equal(auditStatusLabel(true), 'superada');
    assert.ok(!/'fallida'/.test(tickerPage), 'la ficha de empresa aún dice «fallida»');
    assert.match(sourcesPage, /auditStatusLabel\(audit\.passed(, locale)?\)/);
    assert.match(tickerPage, /auditStatusLabel\(audit\.passed(, locale)?\)/);
});

test('ambas páginas componen la puntuación con auditScoreText', () => {
    assert.match(sourcesPage, /auditScoreText\(audit\.passed, audit\.source_coverage_score/);
    assert.match(tickerPage, /auditScoreText\(audit\.passed, audit\.source_coverage_score/);
});

test('ancla de verdad: el backend sigue pudiendo bloquear con puntuación alta', () => {
    // passed ignora solo unsupported/conflicts/fixes; el score no descuenta
    // conflictos ni traza ausente. Si esto cambia, el copy debe revisarse.
    assert.match(backend, /passed = not unsupported and not conflicts and not fixes/);
    assert.match(backend, /source_coverage_score = max\(0, round\(100 \* covered_count \/ material_count\) - len\(weak\) \* 5\)/);
});

test('los motivos del backend se muestran en español y lo desconocido tal cual', () => {
    assert.match(auditFixLabel('No calculation trace -> no valuation.'), /faltan variables de entrada/);
    assert.match(auditFixLabel('Add source_id to every material claim.'), /sin fuente/);
    assert.equal(auditFixLabel('otro motivo'), 'otro motivo');
});
