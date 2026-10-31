import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('app/(root)/calendar/resultados/page.tsx', 'utf8');
const list = readFileSync('components/calendar/FollowedEarningsList.tsx', 'utf8');
const tabs = readFileSync('components/calendar/CalendarTabs.tsx', 'utf8');
// Las cadenas visibles viven en el diccionario i18n (carril C); los
// componentes las referencian por clave. El guard verifica ambos extremos.
const esCalendar = JSON.parse(readFileSync('lib/i18n/messages/es/calendar.json', 'utf8'));
const actions = readFileSync('lib/actions/catalysts.actions.ts', 'utf8');

test('resultados seguidos: lee /api/calendar/followed y no inventa horas', () => {
  assert.match(actions, /\/api\/calendar\/followed/);
  assert.match(actions, /session: 'pre_market' \| 'after_market' \| null/);
  assert.doesNotMatch(list, /toLocaleTimeString|\bhora\b.*new Date/);
});

test('resultados seguidos: estimada solo cuando la fuente lo marca', () => {
  assert.match(list, /event\.confirmed === false/);
  assert.match(list, /calendar\.earnings\.estimated/);
  assert.equal(esCalendar.earnings.estimated, 'Estimada');
});

test('resultados seguidos: logos solo via CompanyLogo (FMP + web oficial, gratis) con fallback de iniciales', () => {
  // Nico pidio logos de empresa explicitamente ("consiguelo en todas"): se
  // permiten las imagenes publicas y gratuitas de Financial Modeling Prep y,
  // como segunda fuente, el icono de la PROPIA web de la empresa servido por
  // nuestra ruta /api/logo, con caida a NameAvatar. Proveedores de logos de
  // terceros siguen prohibidos.
  const logo =
    readFileSync('components/calendar/CompanyLogo.tsx', 'utf8') +
    readFileSync('lib/logos/logo-sources.ts', 'utf8') +
    readFileSync('lib/logos/site-icon.ts', 'utf8') +
    readFileSync('app/api/logo/[ticker]/route.ts', 'utf8');
  assert.match(list, /CompanyLogo/);
  assert.match(logo, /financialmodelingprep\.com\/image-stock/);
  assert.match(logo, /\/api\/logo\//);
  assert.match(logo, /NameAvatar/);
  assert.match(logo, /referrerPolicy="no-referrer"/);
  assert.doesNotMatch(list + page + logo, /logo\.clearbit|img\.logo|logo\.dev|unavatar|google\.com\/s2\/favicons/);
});

test('resultados seguidos: la pestaña activa solo se desplaza si no es visible (nearest)', () => {
  // Regresión: el centrado automático recortaba la primera pestaña ("Resultados"
  // quedaba como "os") incluso cuando la activa cabía entera sin scroll.
  assert.doesNotMatch(tabs, /clientWidth - active\.clientWidth\) \/ 2/);
  assert.match(tabs, /left < nav\.scrollLeft/);
  assert.match(tabs, /right > nav\.scrollLeft \+ nav\.clientWidth/);
});

test('resultados seguidos: pestaña propia y activa solo la más específica', () => {
  assert.match(tabs, /\[["\']\/calendar\/resultados["\'], ["\']calendar\.tabs\.resultados["\']\]/);
  assert.equal(esCalendar.tabs.resultados, 'Resultados');
  assert.match(tabs, /activeHref/);
});

test('resultados seguidos: la fuente es visible (title) y el enlace es externo seguro', () => {
  assert.match(list, /rel="noopener noreferrer"/);
});

void test('la tira de Inicio usa logos legibles en movil (no los 20 px de antes)', () => {
  const strip = readFileSync('components/calendar/EarningsDayStrip.tsx', 'utf8');
  assert.ok(strip.includes('size-9'), 'logo de 36 px en movil');
  assert.ok(!strip.includes('size-5 rounded-md'), 'sin el logo diminuto anterior');
  assert.ok(strip.includes('LOGOS_SHOWN = 2'), 'con logos grandes caben 2 + «+N»');
});

void test('la cabecera de la ficha de empresa muestra el logo a la izquierda del ticker', () => {
  const ficha = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
  assert.match(ficha, /import \{ CompanyLogo \} from '@\/components\/calendar\/CompanyLogo'/);
  assert.match(ficha, /<CompanyLogo ticker=\{ticker\} name=\{company\.name \|\| ticker\}/);
});

void test('Catalizadores muestra el logo de cada empresa en su fila (mismo componente que Empresas seguidas)', () => {
  const catalysts = readFileSync('app/(root)/calendar/page.tsx', 'utf8');
  assert.match(catalysts, /import \{ CompanyLogo \} from '@\/components\/calendar\/CompanyLogo'/);
  assert.match(catalysts, /<CompanyLogo ticker=\{event\.ticker\} name=\{event\.ticker\}/);
});

void test('el «Sin eventos» de la tira de Inicio es legible (contraste AA sobre surface-1)', () => {
  const strip = readFileSync('components/calendar/EarningsDayStrip.tsx', 'utf8');
  assert.match(strip, /<span className="mt-1 text-xs text-gray-400">\{ti\('calendar\.strip\.noEvents'\)\}<\/span>/, 'estado vacio en gray-400 (7.4:1 sobre surface-1)');
  assert.equal(esCalendar.strip.noEvents, 'Sin eventos');
  assert.doesNotMatch(strip, /noEvents.*gray-600|gray-600[^>]*>\{ti\('calendar\.strip\.noEvents'/, 'sin gray-600 (1.8:1) en el estado vacio');
});
