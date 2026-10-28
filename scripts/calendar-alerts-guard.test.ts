// Guard pieza 5: calendario de resultados (cartera + watchlist US) y alertas
// en un solo sitio (/calendar), con origen etiquetado y degradacion honesta.
import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const page = readFileSync('app/(root)/calendar/page.tsx', 'utf8');
const route = readFileSync('data-engine/app/api/routes/calendar.py', 'utf8');
const service = readFileSync('data-engine/app/services/catalyst_calendar_service.py', 'utf8');
const alertsPage = readFileSync('app/(root)/alerts/page.tsx', 'utf8');

test('el calendario cruza resultados de watchlist US etiquetados por origen', () => {
    assert.match(route, /watchlist_us_tickers/);
    assert.match(service, /"origin": "cartera" if in_held else "watchlist"/);
    assert.match(page, /event\.origin === 'watchlist'/);
});

test('resultados y alertas en un solo sitio (/calendar?view=alertas)', () => {
    assert.match(page, /view === 'alertas'/);
    assert.match(page, /AlertsManager/);
    assert.match(page, /Catalizadores de tu cartera/);
});

test('dividendos y plazos siguen siendo solo de cartera', () => {
    assert.match(route, /fetch_dividends_range\(start, end\) if held_us/);
});

test('/alerts enlaza al calendario unificado', () => {
    assert.match(alertsPage, /href="\/calendar"/);
});

test('Calendarios: SectionNav se oculta (CalendarTabs es la única barra) y Cartera es la primera pestaña', () => {
    const sectionNav = readFileSync('components/layout/SectionNav.tsx', 'utf8');
    const tabs = readFileSync('components/calendar/CalendarTabs.tsx', 'utf8');
    assert.match(sectionNav, /CALENDAR_ROUTES=\['\/calendar','\/macro-calendar','\/corporate-actions'\]/);
    assert.match(tabs, /const TABS = \[\s*\["\/portfolio", "Cartera"\]/);
});
