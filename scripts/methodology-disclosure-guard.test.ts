/**
 * Quick win UX 2: los muros de metodología (/propicks, /risk, backtesting)
 * quedan colapsados en un desplegable nativo, cerrado por defecto en todos
 * los viewports; el cliente solo resuelve el texto traducido.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// Los textos de Pro Picks viven en el diccionario es (i18n): se comprueban junto al código.
const ES_PROPICKS_JSON = readFileSync('lib/i18n/messages/es/propicks.json', 'utf8');

const disclosure = readFileSync('components/ui/methodology-disclosure.tsx', 'utf8');
const propicks = (readFileSync('app/(root)/propicks/page.tsx', 'utf8') + ES_PROPICKS_JSON);
const risk = readFileSync('app/(root)/risk/page.tsx', 'utf8');
// Las cadenas visibles de /risk viven en el diccionario i18n (carril C); la
// página las referencia por clave. El guard verifica ambos extremos.
const esRisk = JSON.parse(readFileSync('lib/i18n/messages/es/risk.json', 'utf8'));
const esPortfolio = JSON.parse(readFileSync('lib/i18n/messages/es/portfolio.json', 'utf8'));
const walkforward = (readFileSync('components/proPicks/WalkForwardResults.tsx', 'utf8') + ES_PROPICKS_JSON);

test('el desplegable es nativo, sin estado de apertura JS y cerrado por defecto', () => {
    assert.doesNotMatch(disclosure, /useState|useReducer|onClick|onToggle|onKeyDown/, 'la apertura es nativa, no controlada por JS');
    assert.ok(disclosure.includes("title ?? t('ui.methodologyDisclosure')"));
    for (const [locale, expected] of [['es', 'Metodología y límites'], ['en', 'Methodology and limits']]) {
        assert.equal(JSON.parse(readFileSync(`lib/i18n/messages/${locale}/ui.json`, 'utf8')).methodologyDisclosure, expected);
    }
    assert.match(disclosure, /<details className="group /);
    assert.match(disclosure, /<summary /);
    assert.ok(!/<details[^>]*\bopen\b/.test(disclosure), 'no debe abrirse por defecto en ningún viewport');
    // Chevron rota solo cuando el details está abierto (group-open).
    assert.match(disclosure, /group-open:rotate-180/);
    // El icono de ayuda marca el patrón «?».
    assert.match(disclosure, /CircleHelp/);
});

test('propicks colapsa el muro del embudo y mantiene su copy íntegro', () => {
    assert.match(propicks, /<MethodologyDisclosure>/);
    assert.match(propicks, /import \{ MethodologyDisclosure \} from '@\/components\/ui\/methodology-disclosure';/);
    // El copy explicativo no se borra: se mueve dentro del desplegable.
    assert.match(propicks, /El embudo v1 puntúa cada categoría cuando hay datos/);
    assert.match(propicks, /baseline\s+walk-forward aparte/);
    // Y ya no es un párrafo suelto en la cabecera.
    assert.ok(!/<p className="text-sm text-gray-500">/.test(propicks), 'queda un muro suelto en la cabecera de propicks');
});

test('risk deja una línea de orientación y colapsa alcance y límites', () => {
    assert.match(risk, /<MethodologyDisclosure title=\{t\('risk\.methodology\.title'\)\}>/);
    assert.equal(esRisk.methodology.title, 'Alcance y límites');
    // La orientación de una línea sigue visible.
    assert.match(risk, /risk\.header\.subtitle/);
    assert.match(esRisk.header.subtitle, /Pesos, concentración \(top 1 y top 5\)/);
    // El detalle (qué NO calcula + salidas) vive dentro del desplegable.
    assert.match(risk, /risk\.methodology\.noRiskMeasures/);
    assert.match(esRisk.methodology.noRiskMeasures, /Esta página no calcula volatilidad, drawdown ni VaR/);
});

test('portfolio Resumen: banner sin frase de arquitectura, enlaces intactos', () => {
    const tabs = readFileSync('components/portfolio/PortfolioTabs.tsx', 'utf8');
    assert.ok(!tabs.includes('están fuera de la cartera: en su propia'), 'la app no se explica a sí misma en el banner');
    // El subtítulo vive en el diccionario i18n (carril C); el código lo referencia por clave.
    assert.match(tabs, /portfolio\.tabs\.riskLinksTitle/);
    assert.equal(esPortfolio.tabs.riskLinksTitle, 'Riesgo y exposiciones, en detalle:');
    // Los dos enlaces de navegación se mantienen.
    assert.match(tabs, /href="\/portfolio\/intelligence"/);
    assert.match(tabs, /href="\/risk"/);
});

test('risk: el kicker no duplica el H1', () => {
    // Kicker «Cartera · Exposiciones» + H1 «Exposiciones de cartera» decían lo
    // mismo dos veces seguidas; el kicker nombra solo la sección.
    assert.match(risk, /<p className="text-sm font-semibold uppercase text-teal-300">\{t\('risk\.header\.eyebrow'\)\}<\/p>/);
    assert.equal(esRisk.header.eyebrow, 'Cartera');
    assert.ok(!risk.includes('Cartera · Exposiciones') && !JSON.stringify(esRisk.header).includes('Cartera · Exposiciones'), 'kicker duplicado con el H1');
});

test('el backtesting colapsa su bloque Metodología', () => {
    assert.match(walkforward, /<MethodologyDisclosure title="Metodología del backtest">/);
    assert.match(walkforward, /Walk-forward mensual: cada corte usa únicamente precios de cierre anteriores/);
    // Sin cabecera duplicada del bloque antiguo.
    assert.ok(!/<h4 className="text-sm font-semibold text-gray-300">Metodología<\/h4>/.test(walkforward));
});
