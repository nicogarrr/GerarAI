import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { CHAT_INTENTS, chatIntentHref } from '../lib/research/chat-intents.ts';

/**
 * Guard del asistente por intención (WorldStocks punto 4): los atajos
 * Entender / Revisar supuestos / Cuestionar del chat de la ficha solo
 * formulan preguntas guiadas contra el mismo contrato de evidencia; nunca
 * pintan respuestas prefabricadas.
 */
const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const links = readFileSync('components/research/ChatIntentLinks.tsx', 'utf8');

const form = readFileSync('components/research/CompanyChatForm.tsx', 'utf8');

describe('chat de la ficha: asistente por intención', () => {
    it('existen las 3 intenciones con su etiqueta en español', () => {
        assert.deepEqual(CHAT_INTENTS.map((i) => i.label), ['Entender', 'Revisar supuestos', 'Cuestionar']);
    });
    it('cada intención es una pregunta, nunca una respuesta prefabricada', () => {
        for (const intent of CHAT_INTENTS) {
            const q = intent.question('AAPL');
            assert.ok(q.startsWith('¿') && q.endsWith('?'), `no es una pregunta: ${q}`);
            assert.ok(q.includes('AAPL'), `la pregunta no nombra al ticker: ${q}`);
        }
    });
    it('los atajos lanzan el chat real con la pregunta codificada en la URL', () => {
        const href = chatIntentHref('AAPL', CHAT_INTENTS[0]);
        assert.match(href, /^\/research\/AAPL\?view=chat&chat=/);
        assert.ok(href.includes(encodeURIComponent(CHAT_INTENTS[0].question('AAPL'))));
        assert.match(links, /CHAT_INTENTS\.map/);
        assert.match(links, /chatIntentHref\(ticker, intent\)/);
    });
    it('la ficha monta los atajos y el formulario libre sigue intacto', () => {
        assert.match(page, /<ChatIntentLinks ticker=\{ticker\} \/>/);
        assert.match(page, /<CompanyChatForm ticker=\{ticker\}/);
        assert.match(form, /<Input name="chat"/);
        assert.match(form, /<input type="hidden" name="view" value="chat" \/>/);
    });
    it('al enviar, el navegador vuelve al panel del chat y los atajos también', () => {
        assert.match(chatIntentHref('AAPL', CHAT_INTENTS[0]), /#chat-empresa$/);
        assert.match(page, /id="chat-empresa"/);
        assert.match(form, /action=\{`\/research\/\$\{encodeURIComponent\(ticker\)\}#chat-empresa`\}/);
    });
    it('un fallo del chat no tapa la página con BackendOffline: aviso dentro del panel y campo visible', () => {
        const chatBlock = page.slice(page.indexOf('let chatFailed = false;'), page.indexOf('content = (', page.indexOf('let chatFailed = false;')));
        assert.ok(!chatBlock.includes('BackendOffline'));
        assert.match(chatBlock, /chatFailed = true/);
    });
});
