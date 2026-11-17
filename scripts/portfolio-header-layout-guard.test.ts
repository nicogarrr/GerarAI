import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const tabs = readFileSync('components/portfolio/PortfolioTabs.tsx', 'utf8');

test('F280: el header de /portfolio apila título y acciones hasta lg', () => {
    // A 768px (md) la fila sm:flex-row repartía el ancho entre el bloque del
    // título (min-w-0) y los 4 controles, y «Mi Cartera» se partía en dos
    // líneas. Hasta lg el header va en columna: título completo y acciones
    // debajo a todo el ancho.
    assert.match(tabs, /flex flex-col gap-4 mb-6 lg:flex-row lg:items-center lg:justify-between/);
    assert.doesNotMatch(tabs, /gap-4 mb-6 sm:flex-row/);
});

const summary = readFileSync('components/portfolio/PortfolioSummary.tsx', 'utf8');

test('F328: los importes del resumen se escalan a 360px en vez de recortarse', () => {
    // La grid-cols-2 a 360px deja cada tarjeta en ~164px y overflow-hidden
    // recortaba el importe (~21.5px): text-base -> text-lg -> text-2xl.
    const escalados = summary.match(/text-base min-\[420px\]:text-lg sm:text-2xl font-bold/g) ?? [];
    assert.equal(escalados.length, 4);
    assert.doesNotMatch(summary, /text-xl sm:text-2xl font-bold/);
});

const addBtn = readFileSync('components/portfolio/AddTransactionButton.tsx', 'utf8');
const allocation = readFileSync('components/portfolio/PortfolioAllocation.tsx', 'utf8');

test('F336: «Añadir inversión» envuelve su texto a 360px en vez de recortarse', () => {
    // La celda grid-cols-2 a 360px dejaba el botón con clientWidth 140 <
    // scrollWidth 147 (texto nowrap recortado). <sm envuelve; sm+ intacto.
    assert.match(addBtn, /whitespace-normal[\s\S]*?sm:whitespace-nowrap/);
    assert.match(addBtn, /min-h-\[44px\]/);
});

test('F337: donut y leyenda apilan en móvil en vez de recortar la leyenda', () => {
    // La fila pie 250px + leyenda min-w-140px = 390px > ancho útil a 360-390.
    assert.match(allocation, /flex-1 flex flex-col items-center justify-center gap-6/);
    assert.match(allocation, /h-\[200px\] w-\[200px\] flex-shrink-0 sm:h-\[250px\] sm:w-\[250px\]/);
    assert.doesNotMatch(allocation, /sm:flex-row sm:justify-between/);
    // La reserva del FAB solo aplica desde md: a 360px la leyenda usa todo el ancho.
    assert.doesNotMatch(allocation, /sm:w-auto sm:min-w-\[160px\]/);
    // PC (11 oct): la leyenda se salía de la tarjeta y los porcentajes
    // quedaban cortados. En sm+ la tarjeta crece (sin scroll) y el pct va
    // con flex-shrink-0 + whitespace-nowrap: nunca clippado.
    assert.match(allocation, /max-h-\[250px\] w-full min-w-0 space-y-3 overflow-y-auto sm:max-h-none sm:overflow-visible md:pr-24/);
    assert.match(allocation, /flex-shrink-0 whitespace-nowrap text-sm text-gray-400 tabular-nums/);
});

test('F337: el donut escala con el wrapper (sin radios ni skeleton fijos)', () => {
    const chart = readFileSync('components/portfolio/PortfolioAllocationChart.tsx', 'utf8');
    const panel = readFileSync('components/portfolio/PortfolioAllocation.tsx', 'utf8');
    // Radios fijos (70/105 -> 210px) recortaban el donut en el wrapper de
    // 200px bajo sm; porcentajes de recharts escalan con el contenedor.
    assert.match(chart, /innerRadius="56%"/);
    assert.match(chart, /outerRadius="84%"/);
    assert.doesNotMatch(chart, /innerRadius=\{\d+\}/);
    assert.doesNotMatch(chart, /outerRadius=\{\d+\}/);
    // El placeholder de carga hereda el tamaño del wrapper: fijo a 250px
    // desbordaba 50px a 360px.
    assert.match(panel, /h-full w-full animate-pulse rounded-full/);
    assert.doesNotMatch(panel, /h-\[250px\] w-\[250px\] animate-pulse/);
});
