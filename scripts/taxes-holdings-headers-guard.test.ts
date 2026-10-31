import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const taxes = readFileSync('components/taxes/TaxesView.tsx', 'utf8');
const recordViews = readFileSync('components/data/RecordViews.tsx', 'utf8');
// Las etiquetas visibles viven en el diccionario i18n (carril C); el
// componente las referencia por clave. El guard verifica ambos extremos.
const esTaxes = JSON.parse(readFileSync('lib/i18n/messages/es/taxes.json', 'utf8'));

test('F284: /taxes etiqueta las cinco columnas fiscales visibles en español', () => {
    for (const [key, dictKey, label] of [
        ['ticker', 'ticker', 'Ticker'],
        ['quantity', 'quantity', 'Cantidad'],
        ['cost_basis', 'costBasis', 'Base de coste'],
        ['market_value', 'marketValue', 'Valor de mercado'],
        ['unrealized_pnl', 'unrealizedPnl', 'Plusvalía latente'],
    ] as const) {
        assert.match(taxes, new RegExp(`${key}: ti\\('taxes\\.holdings\\.${dictKey}'\\)`), `falta referencia ${key}`);
        assert.equal(esTaxes.holdings[dictKey], label, `etiqueta es de ${key}`);
    }
});

test('F284: RecordList usa las etiquetas en desktop y móvil, con fallback a la clave cruda', () => {
    // Cabecera <th> (desktop) y <dt> (cards móviles) usan el mapa; las claves
    // sin etiqueta siguen mostrándose crudas, nunca se ocultan.
    assert.equal(recordViews.match(/columnLabels\?\.\[column\] \?\? column/g)?.length, 2);
});

test('F284: la prop es opcional y tipada', () => {
    assert.match(recordViews, /columnLabels\?: Record<string, string>;/);
});
