import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('app/(root)/calendar/resultados/page.tsx', 'utf8');
const list = readFileSync('components/calendar/FollowedEarningsList.tsx', 'utf8');
const tabs = readFileSync('components/calendar/CalendarTabs.tsx', 'utf8');
const actions = readFileSync('lib/actions/catalysts.actions.ts', 'utf8');

test('resultados seguidos: lee /api/calendar/followed y no inventa horas', () => {
  assert.match(actions, /\/api\/calendar\/followed/);
  assert.match(actions, /session: 'pre_market' \| 'after_market' \| null/);
  assert.doesNotMatch(list, /toLocaleTimeString|\bhora\b.*new Date/);
});

test('resultados seguidos: estimada solo cuando la fuente lo marca', () => {
  assert.match(list, /event\.confirmed === false/);
  assert.match(list, /Estimada/);
});

test('resultados seguidos: logos solo via CompanyLogo (FMP, gratis) con fallback de iniciales', () => {
  // Nico pidio logos de empresa explicitamente: se permiten SOLO las imagenes
  // publicas y gratuitas de Financial Modeling Prep dentro de CompanyLogo, con
  // caida a NameAvatar. Otros proveedores de logos siguen prohibidos.
  const logo = readFileSync('components/calendar/CompanyLogo.tsx', 'utf8');
  assert.match(list, /CompanyLogo/);
  assert.match(logo, /financialmodelingprep\.com\/image-stock/);
  assert.match(logo, /NameAvatar/);
  assert.match(logo, /referrerPolicy="no-referrer"/);
  assert.doesNotMatch(list + page + logo, /logo\.clearbit|img\.logo|logo\.dev|unavatar|google\.com\/s2\/favicons/);
});

test('resultados seguidos: pestaña propia y activa solo la más específica', () => {
  assert.match(tabs, /\["\/calendar\/resultados", "Resultados"\]/);
  assert.match(tabs, /activeHref/);
});

test('resultados seguidos: la fuente es visible (title) y el enlace es externo seguro', () => {
  assert.match(list, /title=\{`Fuente: \$\{event\.source\}`\}/);
  assert.match(list, /rel="noopener noreferrer"/);
});
