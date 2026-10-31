/**
 * F255: la tarjeta «Puntuaciones» de /portfolio?tab=estrategia mostraba
 * cinco columnas con icono + «SIN DATOS» sin nombrar el factor en ninguna
 * parte accesible: al cargar datos nadie sabía qué columna era cuál. La
 * columna sin datos también nombra su factor (y «sin datos» sigue diciendo
 * que no es un 0).
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const component = readFileSync('components/portfolio/PortfolioScores.tsx', 'utf8');
const noDataBranch = component.split("display.kind === 'no-data' ? (")[1]?.split(') : (')[0] ?? '';

test('la rama sin datos nombra el factor de la columna', () => {
    assert.ok(noDataBranch.length > 0, 'rama no-data localizable');
    assert.match(noDataBranch, /\{item\.label\}/);
});

test('«sin datos» se mantiene (una puntuación sin datos no es un 0)', () => {
    // i18n: los textos viven en messages/<locale>/portfolio.json.
    assert.match(noDataBranch, /portfolio\.scoresExtra\.noData/);
    assert.match(component, /portfolio\.scoresExtra\.missingFor/);
    const dict = JSON.parse(readFileSync('lib/i18n/messages/es/portfolio.json', 'utf8'));
    assert.equal(dict.scoresExtra.noData, 'sin datos');
    assert.match(dict.scoresExtra.missingFor, /Una puntuación sin datos no es un 0\./);
});

test('la rama con datos sigue nombrando el factor', () => {
    const dataBranch = component.split(') : (')[1] ?? '';
    assert.match(dataBranch, /\{item\.label\}/);
});
