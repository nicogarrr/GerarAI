/**
 * Guard: una tesis generada sin evidencia ofrece salida hacia la subida de
 * documentos. La ruta no se inventa: es la que ya usa el CTA real de
 * /knowledge (`?tab=subir`). El puente vive en el botón compartido de generación
 * (ficha y vistas de tesis) y, además, en el estado vacío del documento.
 *
 * Ejecución: node --experimental-strip-types --test scripts/thesis-evidence-bridge-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const ROUTE = '/knowledge?tab=subir';
const BTN = readFileSync('components/research/ThesisGenerateButton.tsx', 'utf8');
const FICHA = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const TESIS = readFileSync('app/(root)/research/[ticker]/tesis/page.tsx', 'utf8');
const KNOWLEDGE = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
const HELP = readFileSync('components/help/HelpTabs.tsx', 'utf8');
const ES = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8'));
const EN = JSON.parse(readFileSync('lib/i18n/messages/en/research.json', 'utf8'));
const HELP_ES = JSON.parse(readFileSync('lib/i18n/messages/es/help.json', 'utf8'));
const HELP_EN = JSON.parse(readFileSync('lib/i18n/messages/en/help.json', 'utf8'));

const emptyState = (() => {
    const anchor = "title={t('research.thesisDoc.noPublishedTitle', { ticker })}";
    const at = TESIS.indexOf(anchor);
    assert.ok(at > 0, 'existe el estado vacío de tesis');
    return TESIS.slice(at - 800, at + 200);
})();

describe('puente tesis → evidencia (hallazgo de accesibilidad/findability)', () => {
    it('la ruta de subida es la real del CTA de /knowledge', () => {
        assert.match(KNOWLEDGE, /href="\/knowledge\?tab=subir"/);
    });

    it('la ficha ofrece «Aportar evidencia» junto al botón de generar', () => {
        assert.match(FICHA, /<ThesisGenerateButton/, 'la ficha usa el botón compartido');
        assert.match(BTN, /href="\/knowledge\?tab=subir"/);
        assert.match(BTN, /t\('research\.thesisGenerate\.addEvidence'\)/);
        assert.match(BTN, /t\('research\.thesisGenerate\.evidenceHint'\)/);
        // Se ofrece la salida, no se bloquea la generación con datos parciales:
        // el botón solo se desactiva por ocupación o disponibilidad de la IA,
        // nunca por falta de evidencia.
        assert.match(BTN, /startThesisJob\(ticker, true, crypto\.randomUUID\(\)\)/);
        assert.match(BTN, /disabled=\{busy \|\| !availability\.canStart\}/);
        assert.doesNotMatch(BTN, /disabled=\{[^}]*(evidence|document)/i);
    });

    it('el estado vacío de tesis ofrece el enlace y la explicación', () => {
        assert.match(emptyState, /href="\/knowledge\?tab=subir"/);
        assert.match(emptyState, /t\('research\.thesisGenerate\.addEvidence'\)/);
        assert.match(emptyState, /t\('research\.thesisGenerate\.evidenceHint'\)/);
        assert.match(emptyState, /t\('research\.thesisDoc\.generateFirst'\)/, 'conserva «generar la primera»');
    });

    it('el copy i18n es honesto y no inventa datos', () => {
        assert.equal(ES.thesisGenerate.addEvidence, 'Aportar evidencia');
        assert.equal(EN.thesisGenerate.addEvidence, 'Add evidence');
        assert.match(ES.thesisGenerate.evidenceHint, /datos insuficientes/);
        assert.match(ES.thesisGenerate.evidenceHint, /documentos/);
        assert.match(ES.thesisGenerate.evidenceHint, /trazabilidad/);
        assert.match(EN.thesisGenerate.evidenceHint, /insufficient data/);
        assert.match(EN.thesisGenerate.evidenceHint, /Uploading documents/);
        assert.match(EN.thesisGenerate.evidenceHint, /traceability/);
    });

    it('la guía de primeros pasos incluye la ingesta con terminología real', () => {
        assert.match(HELP, /href="\/knowledge\?tab=subir"/);
        assert.match(HELP, /t\('help\.firstSteps\.evidenceText'\)/);
        assert.match(HELP_ES.firstSteps.evidenceText, /Biblioteca/);
        assert.match(HELP_ES.firstSteps.evidenceText, /«Subir»/);
        assert.match(HELP_EN.firstSteps.evidenceText, /Library/);
        assert.match(HELP_EN.firstSteps.evidenceText, /«Upload»/);
    });
});
