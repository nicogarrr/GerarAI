import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('app/(root)/calendar/page.tsx', 'utf8') + readFileSync('components/calendar/CalendarEvents.tsx', 'utf8');
// Las cadenas visibles viven en el diccionario i18n (carril C); la página
// las referencia por clave. El guard verifica ambos extremos.
const esCatalysts = JSON.parse(readFileSync('lib/i18n/messages/es/calendar.json', 'utf8')).catalysts;

test('calendario: singular/plural y fechas sin mayúscula en la preposición', () => {
  assert.match(page, /calendar\.count === 1 \? ti\('calendar\.catalysts\.countSingular'\) : ti\('calendar\.catalysts\.countPlural'\)/);
  assert.equal(esCatalysts.countSingular, 'evento');
  assert.equal(esCatalysts.countPlural, 'eventos');
  assert.doesNotMatch(page, /font-semibold capitalize/);
  assert.match(page, /first-letter:uppercase/);
});

test('calendario: la fuente de NASDAQ lleva tilde', () => {
  const service = readFileSync('data-engine/app/services/catalyst_calendar_service.py', 'utf8');
  assert.match(service, /SOURCE_NASDAQ = "Calendario público de NASDAQ"/);
});
