import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('app/(root)/calendar/page.tsx', 'utf8');

test('calendario: singular/plural y fechas sin mayúscula en la preposición', () => {
  assert.match(page, /calendar\.count === 1 \? 'evento' : 'eventos'/);
  assert.doesNotMatch(page, /font-semibold capitalize/);
  assert.match(page, /first-letter:uppercase/);
});

test('calendario: la fuente de NASDAQ lleva tilde', () => {
  const service = readFileSync('data-engine/app/services/catalyst_calendar_service.py', 'utf8');
  assert.match(service, /SOURCE_NASDAQ = "Calendario público de NASDAQ"/);
});
