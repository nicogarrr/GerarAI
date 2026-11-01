/**
 * Guard: «Revisar con IA» nunca es un no-op silencioso.
 *
 * Bug QA (2026-10-19, reproducido en prod con la cuenta Instinct Audit): al
 * pulsar «Revisar con IA» la respuesta volvía en segundos con todas las joyas
 * «Sin revisión IA» (la cadena LLM no estaba disponible en ese momento) y la
 * pantalla no decía nada más: el botón parecía roto. Tras cada revisión la
 * vista anuncia el resultado: revisadas X de Y, o que la revisión IA no está
 * disponible y que la lista visible es la determinista.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/propicks-revisar-ia-feedback-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const view = readFileSync('components/proPicks/GemsView.tsx', 'utf8') + JSON.stringify(JSON.parse(readFileSync('lib/i18n/messages/es/propicks.json', 'utf8')).gems);

describe('ProPicks Joyas: «Revisar con IA» informa del resultado', () => {
    it('guarda un estado de revisión tras cada llamada', () => {
        assert.match(view, /useState<string \| null>\(null\)/);
        assert.match(view, /setReviewStatus\(/);
    });

    it('distingue revisión completada de revisión IA no disponible', () => {
        assert.match(view, /Revisión IA completada: \{reviewed\} de \{total\}/);
        assert.match(view, /La revisión IA no está disponible ahora mismo/);
        assert.match(view, /selección determinista/);
    });

    it('el estado se anuncia (aria-live) y no depende de leer cada tarjeta', () => {
        assert.match(view, /aria-live="polite"/);
        assert.match(view, /\{reviewStatus\}/);
    });
});
