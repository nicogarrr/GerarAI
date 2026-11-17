// Guard: el monitor denso de watchlist solo pinta datos con fuente propia
// (market_prices), la tabla de fechas de resultados refrescada dos veces al
// dia desde conectores publicos trazables (Yahoo/NASDAQ/manual) o tesis
// publicada. NUNCA una consulta en vivo a un proveedor dentro de la peticion:
// ponia hasta 8 s de red en el TTFB de cada vista de watchlist.
import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const page = readFileSync('app/(root)/watchlist/page.tsx', 'utf8');
const actions = readFileSync('lib/actions/watchlist.actions.ts', 'utf8');
const route = readFileSync('data-engine/app/api/routes/watchlist.py', 'utf8');

test('watchlist page consume el endpoint monitor del backend', () => {
    assert.match(actions, /\/api\/watchlist\/monitor\?tickers=/);
    assert.match(page, /getWatchlistMonitor/);
});

test('proximos resultados y chip 52 semanas vienen del monitor, no hardcodeados', () => {
    const wl = JSON.parse(readFileSync('lib/i18n/messages/es/watchlist.json', 'utf8')).page;
    assert.ok(page.includes("t('watchlist.page.sort.earnings')") && wl.sort.earnings === 'Próx. resultados');
    assert.ok(page.includes("t('watchlist.page.low52')") && wl.low52 === 'Mínimo 52 sem');
    assert.match(route, /EarningsDate/);
    assert.match(route, /is_fresh/);
    assert.doesNotMatch(route, /fetch_earnings_range/);
    assert.match(route, /MarketPrice/);
});

test('el recuento sobre/infravaloradas usa el valor justo ÚNICO con su procedencia', () => {
    const service = readFileSync('data-engine/app/services/fair_value_service.py', 'utf8');
    // La tesis solo cuenta si está PUBLICADA y tiene expected_value real.
    assert.match(service, /status == "published"/);
    assert.match(service, /expected_value\.isnot\(None\)/);
    // El monitor no calcula su propio valor justo: lee el servicio compartido.
    assert.match(route, /resolve_fair_values\(db, companies\)/);
    assert.match(route, /"fair_value_source": reading\["source"\]/);
    assert.match(page, /t\('watchlist\.page\.fairValue\.summary', \{ source: fairValueSourceNote,/);
    const fv = JSON.parse(readFileSync('lib/i18n/messages/es/watchlist.json', 'utf8')).page.fairValue;
    assert.match(fv.summary, /^Según el valor justo \(\{source\}\)/);
    assert.match(fv.byThesis, /con tesis publicada/);
});

test('inicio y screener leen el mismo valor justo único, con etiqueta', () => {
    const screener = readFileSync('lib/actions/screener.actions.ts', 'utf8');
    const home = readFileSync('components/PersonalizedOverview.tsx', 'utf8');
    assert.match(screener, /\/fair-value`/);
    assert.match(home, /home\.opportunities\.source/);
    const dict = JSON.parse(readFileSync('lib/i18n/messages/es/home.json', 'utf8'));
    assert.equal(dict.opportunities.source, 'Fuente: {label}');
});

test('sin URLs de proveedor construidas a mano en el frontend', () => {
    assert.doesNotMatch(page, /nasdaq\.com|finance\.yahoo\.com/);
});

test('el resumen del monitor reserva su altura mientras llega por streaming (sin CLS)', () => {
    // Sin la reserva, la llegada de la franja "Según el valor justo…" empujaba
    // título, botón de alta y tabla: CLS 0.164-0.176 medido en prod a 390x844
    // (17-nov-2026). Las min-h replican las líneas medidas del resumen
    // (text-xs = 16px/línea): 3 en móvil, 2 en sm, 1 en lg.
    assert.match(page, /const rankSummarySlotClass = "min-h-16 text-xs @min-\[344px\]:min-h-12 @min-\[640px\]:min-h-8 @min-\[1216px\]:min-h-4"/);
    // La franja resuelta lleva LAS MISMAS min-h: sin ellas, al ser mas corta
    // que la reserva, el contenido subia al llegar (replica medida 17-nov-2026).
    assert.match(page, /className=\{`\$\{rankSummarySlotClass\} text-gray-500`\}/);
    // Sin ranks validos (ranked=0) la franja resuelve a la misma reserva, no a
    // null: con null la reserva colapsaba al resolver el stream y el contenido
    // subia (CLS inverso, hallazgo del auditor 17-nov-2026).
    assert.match(page, /: rankSummarySlot;/);
    // Con watchlist vacia no hay franja posible: no se reserva nada.
    assert.match(page, /watchlistStocks\.length > 0 && monitorEl\(rankSummaryEl, rankSummarySlot\)/);
    // La cabecera se rige por ANCHO DISPONIBLE (@container), no de ventana, y
    // la reserva cubre el PEOR CASO de texto (~176 chars), no el actual:
    // breakpoints de ventana o alturas por texto real no convergen (NO FAV del
    // auditor a v3 y v4, 17-nov-2026).
    assert.match(page, /<div className="@container flex min-w-0 flex-wrap items-center justify-between gap-3">/);
    // El boton de alta vive SIEMPRE en su propia fila (columna w-full): en
    // linea con la franja, su wrap dependia del largo del texto y no convergia
    // (NO FAV auditor v4: +56px a 1440 con la franja larga, 17-nov-2026).
    assert.match(page, /<div className="min-w-0 w-full">/);
});
