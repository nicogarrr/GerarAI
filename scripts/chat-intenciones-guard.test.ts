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

const form = readFileSync('components/research/BrainAskForm.tsx', 'utf8');
const legacy = readFileSync('components/research/LegacyChatRedirect.tsx', 'utf8');

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
    it('los atajos abren el Cerebro con el ticker y la pregunta, no un chat propio', () => {
        assert.match(links, /CHAT_INTENTS\.map/);
        assert.match(links, /openBrain\(\{ ticker, question: intent\.question\(ticker\) \}\)/);
        assert.doesNotMatch(links, /next\/link/);
    });
    it('la ficha monta atajos y formulario que abren el Cerebro; no queda formulario GET ni llamada al motor', () => {
        assert.match(page, /<ChatIntentLinks ticker=\{ticker\} \/>/);
        assert.match(page, /<BrainAskForm ticker=\{ticker\} \/>/);
        assert.match(form, /openBrain\(\{ ticker, question: text \}\)/);
        assert.doesNotMatch(form, /next\/form/);
        assert.doesNotMatch(page, /CompanyChatForm|askResearchCompanyChat|chatPromise/);
    });
    it('los enlaces antiguos ?chat= abren el Cerebro y limpian el parametro', () => {
        assert.match(page, /<LegacyChatRedirect ticker=\{ticker\} question=\{query\.chat\} \/>/);
        assert.match(legacy, /openBrain\(\{ ticker, question: text\.slice\(0, 2000\) \}\)/);
        // El chat es la sección de la pestaña Fuentes desde el 29-oct-2026.
        assert.match(legacy, /router\.replace\(`\$\{pathname\}\?view=fuentes#chat`/);
        assert.match(chatIntentHref('AAPL', CHAT_INTENTS[0]), /^\/research\/AAPL\?view=fuentes&chat=/);
    });
});
