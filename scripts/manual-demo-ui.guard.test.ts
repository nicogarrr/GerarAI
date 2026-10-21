/**
 * Guard de la pantalla de la cuenta demo manual: la honestidad de la demo
 * no depende de la memoria de quien edite, sino de este test.
 *
 * - La ruta existe y es dinámica (estado por usuario, nada de caché).
 * - Los fixtures de desarrollo NO pueden colarse a producción: la página
 *   solo los sirve cuando NODE_ENV !== 'production'.
 * - La pantalla etiqueta el origen manual simulado y no promete ejecución
 *   de mercado, feed en tiempo real ni equivalencia con un broker.
 * - Los componentes son presentacionales: no importan mongoose ni actions.
 */
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import test from 'node:test';

const PAGE = 'app/(root)/paper-trading/page.tsx';
const COMPONENTS_DIR = 'components/paper-trading';

test('la ruta /paper-trading existe, es dinámica y etiqueta la demo', () => {
    const page = readFileSync(PAGE, 'utf8');
    assert.match(page, /export const dynamic = 'force-dynamic'/, 'la página debe ser dinámica');
    assert.match(page, /NODE_ENV !== 'production'/, 'los fixtures deben quedar fuera de producción');
    assert.match(page, /ficticio/i, 'la página debe declarar el dinero ficticio');
});

test('la UI declara el origen manual simulado sin prometer ejecución real', () => {
    const panel = readFileSync(`${COMPONENTS_DIR}/ManualDemoPanel.tsx`, 'utf8');
    assert.match(panel, /ficticio/i, 'el panel debe declarar el saldo ficticio');
    assert.match(panel, /no es una ejecución de\s+mercado/i, 'debe negar la ejecución de mercado');
    const ledger = readFileSync(`${COMPONENTS_DIR}/LedgerTable.tsx`, 'utf8');
    assert.match(ledger, /Manual simulada/, 'cada fila ejecutada etiqueta su fuente');
    assert.match(ledger, /Rechazada/, 'las órdenes rechazadas llevan badge propio');
    assert.match(ledger, /rejectReason/, 'las rechazadas muestran el motivo, nunca un fill');
    const ticket = readFileSync(`${COMPONENTS_DIR}/OrderTicket.tsx`, 'utf8');
    assert.match(ticket, /no es una ejecución de\s+mercado/i, 'el ticket advierte del fill manual');
    assert.doesNotMatch(ticket, /orderType|limitPrice/, 'sin órdenes límite ficticias en el ticket manual');
});

test('los componentes de la demo son presentacionales (sin servidor dentro)', () => {
    for (const file of readdirSync(COMPONENTS_DIR)) {
        if (!file.endsWith('.tsx')) continue;
        const source = readFileSync(`${COMPONENTS_DIR}/${file}`, 'utf8');
        assert.doesNotMatch(source, /mongoose|manual-demo\.model|lib\/actions\//, `${file} no debe importar servidor`);
    }
});
