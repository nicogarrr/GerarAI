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

// @ts-expect-error TS5097: la extensión .ts explícita la exige node --experimental-strip-types.
import { clientOrderIdAfter, parseEsNumber, type SubmitResult } from '../components/paper-trading/submit.ts';

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

/* ------------------------------------------------------------------ */
/* Parser numérico de entrada: tabla de la semántica acordada.         */
/* Semilla: auditor independiente (29 casos ejecutados sobre 4b9e7e9f).*/
/* ------------------------------------------------------------------ */

const PARSE_VALIDOS: Array<[string, number]> = [
    ['0.001', 0.001],
    ['1.234', 1.234], // un separador = SIEMPRE decimal; nunca 1234
    ['1,234', 1.234],
    ['1.000', 1], // contrato: no hay miles en entrada
    ['1,000', 1],
    ['12.34', 12.34],
    ['1234,56', 1234.56],
    ['1234.56', 1234.56],
    ['0', 0],
    ['-5', -5],
    [' 12.5 ', 12.5], // trim SOLO en extremos (pegar desde otra app)
];

const PARSE_RECHAZADOS: string[] = [
    '1.234,56', // dos tipos de separador: ambigua
    '1,234.56',
    '1,2,3',
    '1.234.567',
    '1.234.567,89',
    '1 234,5', // miles encubierto con espacio: se rechaza, no se fusiona
    '1 2', // NO es 12
    '12 3',
    '',
    ' ',
    'abc',
    '12.',
    '.5',
    ',5',
    '1..2',
    '1e3',
    'Infinity',
    '0x10',
];

test('parseEsNumber: un separador siempre decimal, sin miles, espacios internos rechazados (semilla auditor, 29 casos)', () => {
    assert.equal(PARSE_VALIDOS.length + PARSE_RECHAZADOS.length, 29, 'la tabla cubre los 29 casos de la semilla');
    for (const [input, expected] of PARSE_VALIDOS) {
        assert.equal(parseEsNumber(input), expected, `"${input}" debe valer ${expected}`);
    }
    for (const input of PARSE_RECHAZADOS) {
        assert.ok(Number.isNaN(parseEsNumber(input)), `"${input}" debe rechazarse (NaN), vino ${parseEsNumber(input)}`);
    }
});

/* ------------------------------------------------------------------ */
/* Idempotencia del clientOrderId tras cada resultado (U1)             */
/* ------------------------------------------------------------------ */

type OkResult = Extract<SubmitResult, { ok: true }>;
const STATE = {} as OkResult['state'];
const NUEVO = () => 'ID-NUEVO';

function resultado(outcome: OkResult['outcome'], reason: string | null): SubmitResult {
    return { ok: true, outcome, reason, state: STATE };
}

test('idempotencia U1: rechazo confirmado -> id nuevo (corregir y reenviar ejecuta)', () => {
    // repro U1: rejected persistido, el usuario corrige y reenvía; con el id
    // viejo el servidor respondía duplicate y la orden válida nunca ejecutaba.
    assert.equal(clientOrderIdAfter(resultado('rejected', 'saldo insuficiente'), 'ID-VIEJO', NUEVO), 'ID-NUEVO');
    assert.equal(clientOrderIdAfter(resultado('filled', null), 'ID-VIEJO', NUEVO), 'ID-NUEVO');
});

test('idempotencia U1: duplicate de rechazo muestra reason y permite intento corregido', () => {
    assert.equal(clientOrderIdAfter(resultado('duplicate', 'saldo insuficiente'), 'ID-VIEJO', NUEVO), 'ID-NUEVO');
});

test('idempotencia U1: duplicate de fill y fallo desconocido conservan el id', () => {
    // doble click / reintento de red con el mismo id: no puede crear otra orden.
    assert.equal(clientOrderIdAfter(resultado('duplicate', null), 'ID-VIEJO', NUEVO), 'ID-VIEJO');
    // fallo no-ok (red/desconocido): pudo haber fill persistido; regenerar a
    // ciegas crearía dobles órdenes. Reintento idempotente con el mismo id.
    assert.equal(clientOrderIdAfter({ ok: false, error: 'red caída' }, 'ID-VIEJO', NUEVO), 'ID-VIEJO');
});

test('los tickets aplican la política de idempotencia y distinguen el duplicate de rechazo', () => {
    for (const file of ['OrderTicket.tsx', 'FxTicket.tsx']) {
        const source = readFileSync(`${COMPONENTS_DIR}/${file}`, 'utf8');
        assert.match(source, /clientOrderIdAfter\(result, clientOrderId\.current, newClientOrderId\)/, `${file}: la rotación pasa por el helper`);
        assert.match(source, /outcome === 'duplicate'[\s\S]{0,500}result\.reason/, `${file}: el duplicate distingue reason persistido`);
        // el fallo no-ok conserva el id: sin regeneración en esa rama
        assert.doesNotMatch(source, /setSubmitError\(result\.error\);[\s\S]{0,150}newClientOrderId/, `${file}: el fallo desconocido no regenera el id`);
        // doble click: el botón se deshabilita mientras hay envío en curso
        assert.match(source, /disabled=\{disabled \|\| pending\}/, `${file}: submit deshabilitado durante pending`);
    }
});
