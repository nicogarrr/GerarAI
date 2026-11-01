import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const tickerPage = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
// La credibilidad de la directiva es una sección de Seguimiento desde el 29-oct-2026.
const credibility = readFileSync('components/research/sections/ManagementCredibilitySection.tsx', 'utf8');
const modelPanels = readFileSync('components/research/FundamentalModelPanels.tsx', 'utf8');

// F344/F354/F355 (QA 28/09, viewport 360px): un grid cuyas columnas solo se
// declaran con variantes responsivas (sm:/md:/xl:) no tiene plantilla base,
// y la columna implicita se dimensiona a max-content del contenido: medido
// 349px en una columna de 296 (desborde de pagina de 21px en
// /research/AAPL?view=resumen, 6px en ?view=evidencia, 4px en
// ?view=seguimiento). Todo grid de la ficha lleva base explicita
// (grid-cols-1 = minmax(0, 1fr), que no supera el contenedor).
test('F344/F354/F355: todo grid de la ficha de ticker tiene plantilla de columnas base', () => {
    const offenders: string[] = [];
    for (const match of tickerPage.matchAll(/className="grid([^"]*)"/g)) {
        const classes = match[1];
        if (!/(?<![:\w-])grid-cols-\d/.test(classes)) {
            offenders.push(`grid${classes}`);
        }
    }
    assert.deepEqual(offenders, [], 'grids sin grid-cols-<n> base: ' + offenders.join(' | '));
});

// F355 colo una grid de este componente en #609 (el guard solo leia
// page.tsx): la seccion Diario/Expectativa media 364px a viewport 360.
// El barrido cubre tambien este archivo.
test('F355: todo grid de FundamentalModelPanels tiene plantilla de columnas base', () => {
    const offenders: string[] = [];
    for (const match of modelPanels.matchAll(/className="grid([^"]*)"/g)) {
        const classes = match[1];
        if (!/(?<![:\w-])grid-cols-\d/.test(classes)) {
            offenders.push(`grid${classes}`);
        }
    }
    assert.deepEqual(offenders, [], 'grids sin grid-cols-<n> base: ' + offenders.join(' | '));
});

test('F342: la tabla de escenarios cabe en la pista de laptop (min-w 540, no 640)', () => {
    // Medido en prod a 1366x768: la pista 1.2fr mide ~550px; con min-w-[640px]
    // la cabecera "Valor/acción" quedaba cortada hasta hacer scroll interno.
    assert.match(modelPanels, /<table className="w-full min-w-\[540px\] text-left text-sm">/);
    assert.doesNotMatch(modelPanels, /min-w-\[640px\]/);
});

test('F355: management-credibility declara base grid-cols-1 en el formulario de promesa', () => {
    assert.match(credibility, /mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3/);
});

// F343 (QA 28/09): el boton "Importar afirmaciones de la llamada" hereda
// whitespace-nowrap de Button; su min-content media 337px y desbordaba la
// columna de 296px en /research/AAPL/management-credibility a 360px.
// whitespace-normal (via twMerge) deja que el texto envuelva en movil.
test('F343: el boton de importar afirmaciones permite envolver el texto', () => {
    assert.match(
        credibility,
        /<Button className="h-auto whitespace-normal py-2 text-center" type="submit" variant="outline"><UploadCloud className="h-4 w-4" \/>\{t\('research\.managementSection\.importClaims'\)\}<\/Button>/,
    );
});
