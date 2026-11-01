/**
 * Guard del asistente de investigación (components/brain/BrainGuideAnswer.tsx):
 * una respuesta o sección vacía se explica, no se tapa con «Sin datos».
 *
 * El contrato (lib/research/assistant-contract.ts) permite `answer: ''` y
 * `body: ''`, y distingue `answered` de `insufficient_data`. Antes los tres
 * casos caían al mismo «Sin datos», que no dice si falta el texto, si la
 * evidencia no daba para una conclusión o si el modelo se quedó mudo.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/research-assistant-empty-answer-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync('components/brain/BrainGuideAnswer.tsx', 'utf8');

describe('asistente: respuesta vacía explicada, no tapada con «Sin datos»', () => {
  it('no queda ningún «Sin datos» como respuesta', () => {
    assert.ok(!src.includes("result.answer || 'Sin datos'"), 'la respuesta vacía vuelve al placeholder');
    assert.ok(!src.includes("section.body || 'Sin datos'"), 'la sección vacía vuelve al placeholder');
  });

  it('el texto vacío se decide por el status del contrato', () => {
    assert.match(src, /function emptyAnswerCopy\(t: ReturnType<typeof useT>, status: 'answered' \| 'insufficient_data'\): string/);
    assert.match(src, /function emptySectionCopy\(t: ReturnType<typeof useT>, status: 'answered' \| 'insufficient_data'\): string/);
    assert.match(
      src,
      /result\.answer\?\.trim\(\) \? result\.answer : emptyAnswerCopy\(t, result\.status\)/,
      'la respuesta usa el status, no un literal fijo',
    );
    assert.match(
      src,
      /section\.body\?\.trim\(\) \? section\.body : emptySectionCopy\(t, result\.status\)/,
    );
  });

  it('insufficient_data explica la ausencia y remite a los datos que faltan', () => {
    const guide = JSON.parse(readFileSync('lib/i18n/messages/es/brain.json', 'utf8')).guide;
    assert.ok(guide.emptyAnswerInsufficient.includes('la evidencia disponible no permite confirmar una conclusión'), guide.emptyAnswerInsufficient);
    assert.ok(guide.emptyAnswerInsufficient.includes('Revisa «Datos que faltan»'), guide.emptyAnswerInsufficient);
    assert.ok(src.includes("t('brain.guide.emptyAnswerInsufficient')"));
  });

  it('answered con texto vacío lo dice como lo que es: una respuesta en blanco', () => {
    const guide = JSON.parse(readFileSync('lib/i18n/messages/es/brain.json', 'utf8')).guide;
    assert.ok(guide.emptyAnswer.includes('El asistente ha devuelto la respuesta sin texto'), guide.emptyAnswer);
    assert.ok(guide.emptySection.includes('Sección sin cuerpo: el asistente la ha enviado vacía'), guide.emptySection);
    assert.ok(src.includes("t('brain.guide.emptyAnswer')"));
    assert.ok(src.includes("t('brain.guide.emptySection')"));
  });

  it('un as_of ausente usa el token canónico de fecha, no un «Sin datos»', () => {
    // Con el idioma activo (useT), no con el t() antiguo fijado al español.
    assert.match(src, /citation\.as_of \|\| t\('signals\.noDate'\)/);
    assert.doesNotMatch(src, /legacyT/);
    assert.ok(src.includes('lib/i18n'));
  });
});