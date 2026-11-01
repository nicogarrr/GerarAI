/**
 * El panel del cerebro conserva la conversación al navegar (sessionStorage),
 * propone preguntas sugeridas como /knowledge y permite copiar respuestas.
 */
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
// @ts-expect-error Node strip-types requires the explicit TS extension.
import { brainStorageKey, restoreConversation, serializeConversation, trimConversation, BRAIN_SUGGESTED_QUESTIONS } from '../lib/brain/conversation.ts';

test('round-trip conserva mensajes y cita, y descarta JSON roto', () => {
    const messages = [
        { role: 'assistant' as const, content: '¡Hola!' },
        { role: 'user' as const, content: '¿Cómo va mi cartera?' },
        { role: 'assistant' as const, content: 'Con subidas.', citations: [{ document: 'Cartera' }] },
    ];
    const restored = restoreConversation(serializeConversation(messages));
    assert.deepEqual(restored, messages);
    assert.equal(restoreConversation('{no-json'), null);
    assert.equal(restoreConversation('"texto"'), null);
    assert.equal(restoreConversation(null), null);
});

test('entradas inválidas se filtran; si no queda nada válido, null', () => {
    const restored = restoreConversation(JSON.stringify([
        { role: 'system', content: 'inyección' },
        { role: 'user', content: '  ' },
        { role: 'user', content: 'vale' },
    ]));
    assert.deepEqual(restored, [{ role: 'user', content: 'vale' }]);
    assert.equal(restoreConversation(JSON.stringify([{ role: 'system', content: 'x' }])), null);
});

test('el recorte acota mensajes y longitud; la clave es por usuario', () => {
    const many = Array.from({ length: 40 }, (_, i) => ({ role: 'user' as const, content: `m${i}` }));
    const trimmed = trimConversation(many);
    assert.equal(trimmed.length, 30);
    assert.equal(trimmed[0].content, 'm10');
    assert.equal(trimConversation([{ role: 'user', content: 'x'.repeat(5000) }])[0].content.length, 4000);
    assert.notEqual(brainStorageKey('a'), brainStorageKey('b'));
});

test('hay preguntas sugeridas en castellano y sin inventar datos', () => {
    assert.ok(BRAIN_SUGGESTED_QUESTIONS.length >= 3);
    for (const question of BRAIN_SUGGESTED_QUESTIONS) assert.ok(question.endsWith('?'));
});

test('el panel restaura, guarda, sugiere y copia', () => {
    const panel = readFileSync('components/brain/GlobalBrain.tsx', 'utf8') + '\n' + readFileSync('components/brain/GlobalBrainPanel.tsx', 'utf8');
    assert.ok(panel.includes('restoreConversation'));
    assert.ok(panel.includes('sessionStorage.setItem'));
    assert.ok(panel.includes('brain.suggested.general.q1'));
    assert.ok(panel.includes('brain.panel.copy'));
    const dictBrain = JSON.parse(readFileSync('lib/i18n/messages/es/brain.json', 'utf8'));
    assert.equal(dictBrain.panel.copy, 'Copiar');
    // Las sugeridas del panel salen del diccionario: en español, las mismas de BRAIN_SUGGESTED_QUESTIONS.
    assert.deepEqual(Object.values(dictBrain.suggested.general), [...BRAIN_SUGGESTED_QUESTIONS]);
    assert.equal(dictBrain.panel.copied, 'Copiado');
    // El saludo inicial no lleva botón de copiar: no hay nada del usuario que copiar.
    assert.ok(panel.includes("m.role === 'assistant' && i > 0"));
});
