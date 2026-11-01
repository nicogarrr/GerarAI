import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097
import { missingLayerAction, missingLayerLabel } from '../lib/research/missing-layer-guidance.ts';

const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');

test('F305: cada capa faltante conocida orienta a su propio destino', () => {
    assert.deepEqual(missingLayerAction('KO', 'documents'), {
        href: '/research/KO?view=documents',
        label: 'Importa una fuente primaria',
    });
    assert.deepEqual(missingLayerAction('KO', 'financial_facts'), {
        href: '/research/KO?view=financieros',
        label: 'Refresca los financieros',
    });
    assert.deepEqual(missingLayerAction('KO', 'thesis'), {
        href: '/research/KO?view=tesis',
        label: 'Abre la tesis para generarla',
    });
    assert.deepEqual(missingLayerAction('KO', 'long_term_model'), {
        href: '/research/KO?view=modelo',
        label: 'Genera el modelo',
    });
});

test('F305: una capa desconocida no inventa ruta ni oculta el código', () => {
    assert.equal(missingLayerAction('KO', 'capa_nueva'), null);
    assert.equal(missingLayerLabel('capa_nueva'), 'Capa nueva');
});

test('F305: los tickers con sufijo de mercado se codifican en la ruta', () => {
    assert.equal(missingLayerAction('SAN.MC', 'thesis')?.href, '/research/SAN.MC?view=tesis');
});

test('F305: el aviso de la vista general enlaza capa a capa (no un solo enlace a documentos)', () => {
    assert.match(page, /snapshot\.research_health\.missing\.map\(\(layer\)/);
    assert.match(page, /missingLayerAction\(ticker, layer, t\)/);
    assert.match(page, /missingLayerLabel\(layer, t\)/);
});

test('F309: los estados vacíos de la vista financieros ya no mandan a importar documentos', () => {
    // FactTable vive en FactsPanels (ultima funcion del fichero).
    const panels = readFileSync('components/research/FactsPanels.tsx', 'utf8');
    const factTable = panels.slice(panels.indexOf('export function FactTable'));
    assert.doesNotMatch(factTable, /view=documents/);
    assert.match(factTable, /refreshLabel/);
    assert.match(factTable, /t\('research\.facts\.emptyDescription', \{ label: refreshLabel \}\)/);
    const factsEs = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).facts;
    assert.match(factsEs.emptyDescription, /Pulsa «\{label\}» arriba para traerlos del proveedor indicado/);
    assert.match(factsEs.emptyDescription, /no hay datos persistidos: comprueba el resultado del refresh y la fuente/);
    const metrics = page.slice(page.indexOf('function MetricsGrid'), page.indexOf('function ValuationView'));
    assert.doesNotMatch(metrics, /view=documents/);
    assert.match(metrics, /t\('research\.ficha\.metricsEmptyDescription'\)/);
    const fichaEs = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).ficha;
    assert.match(fichaEs.metricsEmptyDescription, /pulsa «Recalcular» arriba/);
    assert.match(fichaEs.metricsEmptyDescription, /botón de actualización correspondiente/);
    assert.doesNotMatch(fichaEs.metricsEmptyDescription, /fuente oficial/);
    // «Fuente oficial» solo cuando el flujo lo sea: FMP es proveedor comercial.
    assert.doesNotMatch(factTable, /fuente oficial/);
    assert.doesNotMatch(metrics, /fuente oficial/);
});

test('F309: FactTable recibe el nombre exacto del botón de refresh según el mercado', () => {
    assert.match(page, /refreshLabel=\{/);
    assert.match(page, /t\('research\.fichaRefreshFinancialsFmp'\)/);
    assert.match(page, /t\('research\.fichaRefreshEsef'\)/);
    assert.match(page, /t\('research\.fichaRefreshSec'\)/);
});
