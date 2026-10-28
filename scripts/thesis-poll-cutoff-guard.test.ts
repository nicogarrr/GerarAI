/**
 * Guard: el polling de la tesis tiene corte y el corte se declara.
 *
 * El efecto re-agendaba setTimeout(tick, POLL_MS) sin límite: un job
 * atascado (cola envenenada, worker caído sin dispatch_failed) dejaba el
 * botón en «Generando en segundo plano…» para siempre. Ahora hay MAX_POLLS
 * y, al agotarse, el copy pasa a «Estado desconocido» y no se re-agenda.
 *
 * Ejecución: node --experimental-strip-types --test scripts/thesis-poll-cutoff-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const button = readFileSync('components/research/ThesisGenerateButton.tsx', 'utf8');

describe('polling de tesis: corte y estado desconocido', () => {
    it('hay MAX_POLLS y un contador de polls', () => {
        assert.match(button, /const MAX_POLLS = \d+;/);
        assert.match(button, /pollCountRef\.current \+= 1;/);
    });
    it('al agotarse NO se re-agenda y se marca pollExhausted', () => {
        // El agotamiento se marca por id de job (estado derivado, sin reset en efecto).
        assert.match(button, /if \(pollCountRef\.current >= MAX_POLLS\) \{[\s\S]{0,200}setExhaustedJobId\(jobId\);\s*return;/);
        // El efecto no arranca si está agotado.
        assert.match(button, /if \(!active \|\| !jobId \|\| pollExhausted\) return;/);
    });
    it('el copy pasa a «Estado desconocido» y no promete progreso', () => {
        assert.match(button, /Estado desconocido: la generación no responde/);
        assert.match(button, /El trabajo del servidor no se cancela/);
    });
    it('un job nuevo reinicia la ventana de polling', () => {
        // El contador arranca con el efecto de polling y el agotamiento se
        // deriva comparando ids: un job nuevo tiene id distinto, así que su
        // ventana es nueva sin necesidad de un efecto de reset.
        assert.match(button, /pollCountRef\.current = 0;/);
        assert.match(button, /const pollExhausted = jobId != null && exhaustedJobId === jobId;/);
    });
});
