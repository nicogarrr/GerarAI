// Guard: el selector de metrica explica el estado de cobertura vacia conocida
// (options.length === 0) en vez de mostrar un desplegable casi vacio sin
// contexto. No afirma motor caido: solo informa y ofrece la formula.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const picker = readFileSync('components/screeners/FilterFields.tsx', 'utf8');

test('el picker explica el estado sin metricas disponibles', () => {
    assert.match(picker, /options\.length === 0/, 'condicional por lista vacia');
    assert.match(picker, /No hay métricas disponibles\. Puedes crear una fórmula\./, 'copy informativo en ES');
});
