import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/**
 * realqa-15: con la evaluación diaria apagada en el servidor las 19 empresas
 * salían «Sin evaluar» sin ninguna explicación. El panel lo dice en español y
 * apunta a «Evaluar ahora».
 */
const panel = readFileSync('components/watchlist/DcaSignalsPanel.tsx', 'utf8');
const types = readFileSync('lib/dca/types.ts', 'utf8');

describe('panel DCA con la evaluación diaria apagada', () => {
    it('el tipo de respuesta declara evaluation_enabled', () => {
        assert.match(types, /evaluation_enabled\?: boolean;/);
    });
    it('solo avisa cuando el backend dice false explícitamente (backends antiguos: sin aviso)', () => {
        assert.match(panel, /data\.evaluation_enabled === false/);
        assert.match(panel, /data-testid="dca-evaluation-disabled"/);
    });
    it('explica el motivo y el siguiente paso en español', () => {
        // i18n: el texto vive en messages/<locale>/watchlist.json.
        assert.ok(panel.includes("ti('watchlist.dca.panel.evalOffStale')"));
        assert.ok(panel.includes("ti('watchlist.dca.panel.evalOffEmpty')"));
        const esPanel = JSON.parse(readFileSync('lib/i18n/messages/es/watchlist.json', 'utf8')).dca.panel;
        for (const text of [esPanel.evalOffStale, esPanel.evalOffEmpty]) {
            assert.match(text, /evaluación diaria automática está desactivada en el servidor/);
            assert.match(text, /Pulsa «Ejecutar pendientes ahora»/);
        }
        const enPanel = JSON.parse(readFileSync('lib/i18n/messages/en/watchlist.json', 'utf8')).dca.panel;
        assert.match(enPanel.evalOffStale, /Run pending now/);
    });
});
