/**
 * Guarda del feedback compartido de los tickets de la cuenta demo manual:
 * OrderTicket y FxTicket usan el MISMO trio de mensajes (error/aviso/
 * duplicado), el MISMO init del datetime-local y el MISMO helper de error de
 * validacion ligado a los campos, en vez de tres copias que ya se desviaron
 * una vez (la contencion de iOS del datetime-local llego solo a OrderTicket).
 *
 * Ejecución: node --experimental-strip-types --test scripts/paper-ticket-feedback-shared-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const order = readFileSync('components/paper-trading/OrderTicket.tsx', 'utf8');
const fx = readFileSync('components/paper-trading/FxTicket.tsx', 'utf8');
const shared = readFileSync('components/paper-trading/ticket-feedback.tsx', 'utf8');

describe('feedback compartido de los tickets demo', () => {
    it('los dos tickets usan el modulo compartido', () => {
        for (const [name, source] of [['OrderTicket', order], ['FxTicket', fx]] as const) {
            assert.match(source, /from '\.\/ticket-feedback'/, `${name} importa ticket-feedback`);
            assert.match(source, /<TicketFeedbackMessages/, `${name} usa el trio compartido`);
            assert.match(source, /useExecutedAtLocal\(\)/, `${name} usa el init compartido de fecha`);
            assert.match(source, /invalidMessage\(invalid, fieldKey\)/, `${name} usa el helper de validacion`);
        }
    });

    it('el trio de mensajes existe UNA vez, en el modulo compartido', () => {
        assert.match(shared, /role="alert"[\s\S]*role="status"[\s\S]*text-warn/);
        for (const [name, source] of [['OrderTicket', order], ['FxTicket', fx]] as const) {
            assert.doesNotMatch(source, /role="alert"/, `${name} no lleva su propio trio`);
        }
    });

    it('la cascada de resultado y la rotacion del id siguen inline en cada ticket', () => {
        for (const [name, source] of [['OrderTicket', order], ['FxTicket', fx]] as const) {
            assert.match(source, /clientOrderIdAfter\(result, clientOrderId\.current, newClientOrderId\)/, `${name}: rotacion inline`);
            assert.match(source, /outcome === 'duplicate'/, `${name}: rama duplicate inline`);
        }
    });
});
