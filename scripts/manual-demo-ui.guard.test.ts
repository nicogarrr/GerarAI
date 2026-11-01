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
import { clientOrderIdAfter, NUM_INPUT_HINT, parseEsNumber, type SubmitResult } from '../components/paper-trading/submit.ts';

const PAGE = 'app/(root)/paper-trading/page.tsx';

test('NUM_INPUT_HINT coincide con el diccionario i18n', () => {
    const dict = JSON.parse(readFileSync('lib/i18n/messages/es/paperTrading.json', 'utf8'));
    assert.equal(NUM_INPUT_HINT, dict.numInputHint);
});
const COMPONENTS_DIR = 'components/paper-trading';

test('la ruta /paper-trading existe, es dinámica y etiqueta la demo', () => {
    const page = readFileSync(PAGE, 'utf8');
    assert.match(page, /export const dynamic = 'force-dynamic'/, 'la página debe ser dinámica');
    assert.match(page, /NODE_ENV !== 'production'/, 'los fixtures deben quedar fuera de producción');
    // i18n: el copy vive en messages/<locale>/paperTrading.json; la página referencia la clave.
    assert.match(page, /paperTrading\.page\.description/, 'la página referencia la descripción');
    const dict = JSON.parse(readFileSync('lib/i18n/messages/es/paperTrading.json', 'utf8'));
    assert.match(dict.page.description, /ficticio/i, 'la página debe declarar el dinero ficticio');
});

test('el realizado se etiqueta como antes de comisiones en panel y tabla (delta 21-oct-2026)', () => {
    // Verificado en lib/paper-trading/accounting.ts: el FIFO calcula
    // realizado = cantidad x (precio venta - precio lote); las comisiones
    // solo mueven el efectivo. La UI debe decirlo junto a la cifra.
    const dict = JSON.parse(readFileSync('lib/i18n/messages/es/paperTrading.json', 'utf8'));
    const summary = readFileSync(`${COMPONENTS_DIR}/AccountSummary.tsx`, 'utf8');
    // i18n: el hint vive en el diccionario; el código referencia la clave.
    assert.match(summary, /hint=\{ti\('paperTrading\.account\.realizedHint'\)\}/, 'los totales realizados deben llevar el hint');
    assert.equal(dict.account.realizedHint, 'antes de comisiones');
    const table = readFileSync(`${COMPONENTS_DIR}/PositionsTable.tsx`, 'utf8');
    assert.match(table, /paperTrading\.positions\.footnote/, 'la tabla referencia la nota de realizado');
    assert.match(dict.positions.footnote, /Realizado antes de comisiones \(las comisiones solo mueven el efectivo\)/, 'la tabla debe declararlo');
    // Aviso de cuenta (QA live 21-oct-2026): el campo de comisión ya no
    // existe (#2011); el aviso describe el 0 simulado y los históricos sin
    // sugerir tarifa 0 de ningún bróker.
    const actions = readFileSync('lib/actions/manual-demo.actions.ts', 'utf8');
    // Acotado al formulario: la API placeManualOrder aún admite fee>0
    // (auditor 21-oct-2026); el aviso no puede prometer nada del backend.
    assert.match(actions, /las órdenes registradas desde este formulario se anotan con comisión 0 simulada \(simplificación de la demo, no la tarifa de ningún bróker\)/);
    assert.match(actions, /las comisiones históricas registradas se conservan tal cual y solo mueven el efectivo/);
    assert.doesNotMatch(actions, /si introduces una, se registra tal cual/);
});

test('la celda N/D de escritorio no se rompe en líneas: motivo expandible y accesible', () => {
    // QA píxeles 21-oct-2026: el aviso de opción sin valorar forzaba ~8
    // líneas; y title/truncate solo NO vale (auditor): el motivo completo
    // debe ser visible/expandible con teclado y táctil (details nativo).
    // En móvil se muestra entero bajo el nombre.
    const table = readFileSync(`${COMPONENTS_DIR}/PositionsTable.tsx`, 'utf8');
    // i18n: «Motivo» y «Sin valoración.» viven en el diccionario (positions.reasonSummary/noValuation).
    assert.match(table, /<summary className="[^"]*">\{ti\('paperTrading\.positions\.reasonSummary'\)\}<\/summary>/);
    assert.match(table, /<p className="mt-1 max-w-56 whitespace-normal">\{row\?\.note \?\? ti\('paperTrading\.positions\.noValuation'\)\}<\/p>/);
    assert.doesNotMatch(table, /truncate text-xs text-gray-500" title=/);
});

test('la UI declara el origen manual simulado sin prometer ejecución real', () => {
    const dict = JSON.parse(readFileSync('lib/i18n/messages/es/paperTrading.json', 'utf8'));
    const panel = readFileSync(`${COMPONENTS_DIR}/ManualDemoPanel.tsx`, 'utf8');
    // i18n: el copy vive en el diccionario; el código referencia las claves.
    assert.match(panel, /paperTrading\.panel\.intro/, 'el panel referencia su declaración');
    assert.match(dict.panel.intro, /ficticio/i, 'el panel debe declarar el saldo ficticio');
    assert.match(dict.panel.intro, /no es una ejecución de mercado/i, 'debe negar la ejecución de mercado');
    const ledger = readFileSync(`${COMPONENTS_DIR}/LedgerTable.tsx`, 'utf8');
    assert.match(ledger, /paperTrading\.ledger\.manualBadge/, 'cada fila ejecutada referencia su fuente');
    assert.equal(dict.ledger.manualBadge, 'Manual simulada');
    assert.match(ledger, /paperTrading\.ledger\.rejectedBadge/, 'las órdenes rechazadas llevan badge propio');
    assert.equal(dict.ledger.rejectedBadge, 'Rechazada');
    assert.match(ledger, /rejectReason/, 'las rechazadas muestran el motivo, nunca un fill');
    const ticket = readFileSync(`${COMPONENTS_DIR}/OrderTicket.tsx`, 'utf8');
    assert.match(ticket, /paperTrading\.ticket\.manualNote/, 'el ticket referencia la advertencia del fill manual');
    assert.match(dict.ticket.manualNote, /no es una ejecución de mercado/i, 'el ticket advierte del fill manual');
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

test('un rechazo confirmado revalida /paper-trading: el Historial no puede quedarse obsoleto (bug QA live 21-oct-2026)', () => {
    // Repro QA tenant Audit 22:35 CEST: venta BBVA.MC rechazada con ticket
    // correcto -> la fila del rechazo NO aparecía en Historial hasta recargar
    // (persistencia correcta; faltaba revalidación tras el outcome rejected).
    // El fill refresca desde el ticket (router.refresh); el rechazo depende
    // de esta revalidación en la server action. Si alguien la quita, el
    // historial vuelve a quedarse obsoleto sin que ningún otro test lo note.
    const page = readFileSync(PAGE, 'utf8');
    assert.match(page, /import \{ revalidatePath \} from 'next\/cache'/, 'la página debe importar revalidatePath');
    const sites = page.match(/if \(result\.outcome === 'rejected'\) revalidatePath\('\/paper-trading'\)/g) ?? [];
    assert.equal(sites.length, 2, 'submitFill y submitFx deben revalidar tras un rechazo confirmado');
});

test('el historial es paginado: cursor estable cableado página -> panel -> paginación', () => {
    // Read-model paginado (22-oct-2026): la primera página la sirve el
    // server component y las siguientes las pide el panel con el cursor
    // (createdAt, _id); la contabilidad (readLedger) no pasa por aquí.
    const page = readFileSync(PAGE, 'utf8');
    assert.match(page, /manual-demo-history\.actions/, 'la página usa la consulta paginada');
    assert.match(page, /loadMoreHistory=\{loadMoreHistory\}/, 'la página pasa la acción de cargar más');
    assert.match(page, /historyHasMore=\{historyHasMore\}/, 'la página pasa hasMore');
    const panel = readFileSync(`${COMPONENTS_DIR}/ManualDemoPanel.tsx`, 'utf8');
    assert.doesNotMatch(panel, /Cargar más/, 'Nico 2026-10-28: paginación, no «Cargar más»');
    assert.match(panel, /<Pagination[\s\S]*?hasMore=/, 'el panel pagina el historial');
    assert.match(panel, /onLoadMoreHistory/, 'la última página pide el siguiente bloque con el cursor');
    // i18n: el mensaje vive en el diccionario (panel.loadMoreError).
    assert.match(panel, /role="alert"[\s\S]{0,200}paperTrading\.panel\.loadMoreError/, 'un fallo al cargar más es visible');
});
