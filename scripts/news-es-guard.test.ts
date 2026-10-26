/**
 * Quick win UX 4: noticias y fichas siempre en español.
 * - El titular SEC se genera en español, sin ticker ni fecha duplicados.
 * - La línea sector/industria de la ficha se traduce y no se duplica.
 * - Los mensajes de alerta red-team viven en español en el backend (red de
 *   regresión: el inglés no vuelve).
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { sectorIndustryLine } from '../lib/labels.ts';

const sec = readFileSync('data-engine/app/services/connectors/sec.py', 'utf8');
const redTeam = readFileSync('data-engine/app/services/red_team_service.py', 'utf8');

test('el titular SEC es español y no repite ticker ni fecha', () => {
    assert.match(sec, /title = f"\{form or 'filing'\} presentado ante la SEC"/);
    assert.ok(!sec.includes('SEC filing} filed'), 'queda la plantilla inglesa');
    assert.ok(!/\(\{report_date\}\)/.test(sec), 'la fecha no va en el titular (es columna propia)');
    assert.ok(!sec.includes("ticker.upper() + ' '"), 'el ticker no se incrusta en el titular');
});

test('la ficha traduce sector e industria y colapsa duplicados', () => {
    assert.equal(sectorIndustryLine('Information Technology', 'Technology'), 'Tecnología');
    assert.equal(sectorIndustryLine('Health Care', 'Pharmaceuticals'), 'Salud · Farmacéutica');
    assert.equal(sectorIndustryLine('Financials', 'Unknown'), 'Servicios financieros');
    assert.equal(sectorIndustryLine('Communication Services', 'Telecommunication'), 'Servicios de comunicación · Telecomunicaciones');
});

test('los mensajes red-team del backend son españoles (red de regresión)', () => {
    assert.match(redTeam, /La valoración no se puede publicar porque faltan datos necesarios/);
    assert.ok(!redTeam.includes('Valuation is not publishable'), 'inglés de vuelta en red-team');
    assert.ok(!redTeam.includes('Red-team findings for'), 'título de alerta en inglés');
    // Fallback de falsification_tests visible en la ficha cuando ninguna
    // afirmación material trae condiciones de invalidación.
    assert.match(redTeam, /Define condiciones de invalidación explícitas y medibles/);
    assert.ok(!redTeam.includes('Define explicit, measurable'), 'fallback de falsificación en inglés');
});
