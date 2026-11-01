/**
 * Guarda del feedback único del panel de debate (hallazgo designer 2026-10-21):
 * un fallo al generar el debate se muestra UNA vez — bloque inline con
 * mensaje y botón Reintentar — sin toast que repita el mismo error con la
 * misma acción (convención B7 de MutationForm: el toast solo cuando aporta
 * una acción que el inline no tiene; aquí el inline ya la tiene).
 * Ejecución: node --experimental-strip-types --test scripts/thesis-debate-feedback-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(
    new URL('../components/research/ThesisDebatePanel.tsx', import.meta.url),
    'utf8',
);

describe('feedback único del panel de debate', () => {
    it('no dispara toast de error (el bloque inline ya muestra el fallo)', () => {
        assert.doesNotMatch(source, /showErrorToast/);
    });

    it('conserva el bloque inline con el mensaje y el botón Reintentar', () => {
        assert.match(source, /setError\(/);
        assert.match(source, /role="alert"/);
        // El bloque de error lleva el mensaje y su propio botón Reintentar
        // que invoca la misma acción que generaba el debate.
        assert.match(source, /t\('research\.thesisDebate\.failed', \{ error \}\)[\s\S]*?onClick=\{run\}[\s\S]*?t\('research\.thesisDebate\.retry'\)/);
        const debateEs = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).thesisDebate;
        assert.equal(debateEs.failed, 'El debate falló: {error}');
        assert.equal(debateEs.retry, 'Reintentar');
    });

    it('conserva el re-lanzado de redirects de Next (navegación, no error)', () => {
        assert.match(source, /isNextRedirectError\(exc\)\) throw exc/);
    });
});
