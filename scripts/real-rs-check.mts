/**
 * Harness OPT-IN: prueba las acciones demo-manual contra un MongoDB
 * REPLICA SET real (mongodb-memory-server, efímero y local): sobregiro y
 * sobreventa con dos orderIds EN PARALELO, mismo orderId concurrente,
 * aislamiento por usuario y versión condicional. El código bajo prueba es
 * el fuente REAL de producción (acciones + paper-trading + modelo); solo
 * se sustituyen auth (stub) y la conexión (apunta al RS efímero).
 *
 * Ejecución manual (NO entra en `npm run test:guards`: este archivo no
 * sigue el patrón *.test.* que auto-descubre run-guards.mjs):
 *   node --experimental-strip-types scripts/real-rs-check.mts
 *
 * Requisitos: mongodb-memory-server ya es devDependency del repo (la usa
 * scripts/test-auth-signup.mjs en CI); NO añade ninguna dependencia ni
 * cambio de CI. La primera ejecución descarga el binario de MongoDB
 * (~100 MB, cacheado en ~/.cache/mongodb-binaries); las siguientes lo
 * reutilizan. Necesita red solo para esa descarga inicial.
 *
 * Datos: el RS se crea vacío en cada ejecución y se destruye al terminar;
 * usuario ficticio __MANUAL_DEMO_GUARD_USER__. Ningún dato real, ninguna
 * cuenta, ningún secreto (no lee .env ni MONGODB_URI).
 *
 * Qué prueba y qué NO: valida que el CÓDIGO de producción se comporta
 * bien contra un Mongo con transacciones reales; NO prueba la ejecución
 * en producción/Atlas (eso es del owner de despliegue).
 *
 * Última ejecución verificada: 22-oct-2026, origin/main fd86dc9, 9/9 casos.
 */
import { register } from 'node:module';
register('./real-rs-loader.mjs', import.meta.url);

import assert from 'node:assert/strict';
import mongoose from 'mongoose';
import { MongoMemoryReplSet } from 'mongodb-memory-server';

const rs = await MongoMemoryReplSet.create({ replSet: { count: 1, storageEngine: 'wiredTiger' } });
const conn = await import('@/database/mongoose');
(conn as unknown as { __setUri(u: string): void }).__setUri(rs.getUri());

const model = (await import('@/database/models/manual-demo.model')) as unknown as {
    ManualDemoAccount: {
        init(): Promise<unknown>;
        findOne(filter: Record<string, unknown>): Promise<{ version: number; cashEUR: number } | null>;
    };
    ManualDemoTrade: {
        init(): Promise<unknown>;
        countDocuments(filter: Record<string, unknown>): Promise<number>;
        collection: { insertOne(doc: Record<string, unknown>): Promise<unknown> };
    };
};
// @ts-expect-error TS5097
const actions = await import('../lib/actions/manual-demo.actions.ts');

const NOW = Date.now();
let seq = 0;
const oid = () => `real-rs-${++seq}`;
const login = (id: string) => { (globalThis as Record<string, unknown>).__MANUAL_DEMO_GUARD_USER__ = { id, email: `${id}@t`, name: id }; };
const buy = (symbol: string, qty: number, price: number, over: Record<string, unknown> = {}) => ({
    instrument: { kind: 'accion', symbol, name: symbol }, side: 'buy', quantity: qty, price, currency: 'EUR',
    fee: 0, executedAt: NOW - 60_000, clientOrderId: oid(), ...over,
});
const sell = (symbol: string, qty: number, price: number, over: Record<string, unknown> = {}) =>
    buy(symbol, qty, price, { side: 'sell', ...over });

await (conn as unknown as { connectToDatabase(): Promise<unknown> }).connectToDatabase();
console.log('conectado al RS');
await model.ManualDemoAccount.init();
await model.ManualDemoTrade.init();
console.log('RS real levantado:', rs.getUri().split('?')[0]);

// 1) SOBREGIRO: dos compras de 60.000 en paralelo, solo una puede caber.
login('rs-user-a');
const [r1, r2] = await Promise.all([
    actions.placeManualOrder(buy('X.MC', 6000, 10)),
    actions.placeManualOrder(buy('Y.MC', 6000, 10)),
]);
const outcomes = [r1.ok && r1.outcome, r2.ok && r2.outcome].sort();
assert.deepEqual(outcomes, ['filled', 'rejected'], `sobregiro: ${JSON.stringify(outcomes)}`);
const accA = await actions.getManualDemoAccount();
assert.ok(accA.ok);
if (accA.ok) assert.equal(accA.state.cashEUR, 40_000, `cash A: ${accA.state.cashEUR}`);
console.log('1) sobregiro paralelo: OK (una filled, una rejected, cash 40.000)');

// 2) SOBREVENTA: comprar 10 y lanzar dos ventas de 10 en paralelo.
login('rs-user-b');
assert.ok((await actions.placeManualOrder(buy('Z.MC', 10, 10))).ok);
const [s1, s2] = await Promise.all([
    actions.placeManualOrder(sell('Z.MC', 10, 20)),
    actions.placeManualOrder(sell('Z.MC', 10, 20)),
]);
const sellOutcomes = [s1.ok && s1.outcome, s2.ok && s2.outcome].sort();
assert.deepEqual(sellOutcomes, ['filled', 'rejected'], `sobreventa: ${JSON.stringify(sellOutcomes)}`);
const accB = await actions.getManualDemoAccount();
assert.ok(accB.ok);
if (accB.ok) {
    assert.equal(accB.state.cashEUR, 100_100, `cash B: ${accB.state.cashEUR}`);
    assert.equal(accB.state.positions.length, 0);
}
console.log('2) sobreventa paralela: OK (una filled, una rejected, posición 0, cash 100.100)');

// 3) MISMO clientOrderId en paralelo: una filled + una duplicate, UN solo doc, cash movido una vez.
login('rs-user-c');
const same = buy('W.MC', 10, 10, { clientOrderId: oid() });
const [d1, d2] = await Promise.all([actions.placeManualOrder(same), actions.placeManualOrder(same)]);
const dupOutcomes = [d1.ok && d1.outcome, d2.ok && d2.outcome].sort();
assert.deepEqual(dupOutcomes, ['duplicate', 'filled'], `mismo orderId: ${JSON.stringify(dupOutcomes)}`);
const docsC = await model.ManualDemoTrade.countDocuments({ userId: 'rs-user-c' });
assert.equal(docsC, 1, `docs user C: ${docsC}`);
const accC = await actions.getManualDemoAccount();
assert.ok(accC.ok);
if (accC.ok) assert.equal(accC.state.cashEUR, 99_900, `cash C: ${accC.state.cashEUR}`);
console.log('3) mismo clientOrderId concurrente: OK (1 doc, cash descontado una vez)');

// 4) Aislamiento: otro usuario limpio.
login('rs-user-d');
const accD = await actions.getManualDemoAccount();
assert.ok(accD.ok);
if (accD.ok) {
    assert.equal(accD.state.cashEUR, 100_000);
    assert.equal(accD.state.positions.length, 0);
}
console.log('4) aislamiento por usuario: OK');

// 5) Versión condicional real: version == nº de fills aplicados en la cuenta.
const accDocB = await model.ManualDemoAccount.findOne({ userId: 'rs-user-b' });
assert.equal(accDocB?.version, 2, `version B: ${accDocB?.version} (2 fills)`);
const accDocC = await model.ManualDemoAccount.findOne({ userId: 'rs-user-c' });
assert.equal(accDocC?.version, 1, `version C: ${accDocC?.version} (1 fill pese a 2 intentos)`);
// Caché de saldos cuadrada con el libro tras las carreras.
assert.equal(accDocB?.cashEUR, 100_100);
assert.equal(accDocC?.cashEUR, 99_900);
console.log('5) versión condicional + caché de saldos cuadrada: OK');

// 6) R3: compra USD antedatada antes de la conversión que la financia.
login('rs-user-e');
await actions.convertManualDemoCurrency({ from: 'EUR', to: 'USD', amount: 1000, rate: 1.2, executedAt: NOW - 100_000, clientOrderId: oid() });
const back = await actions.placeManualOrder(buy('ASTS', 10, 40, { currency: 'USD', executedAt: NOW - 200_000 }));
assert.ok(back.ok);
if (back.ok) assert.equal(back.outcome, 'rejected', `antedatada: ${JSON.stringify(back)}`);
const okAfter = await actions.placeManualOrder(buy('ASTS', 10, 40, { currency: 'USD', executedAt: NOW - 50_000 }));
assert.ok(okAfter.ok);
if (okAfter.ok) {
    assert.equal(okAfter.outcome, 'filled');
    assert.equal(okAfter.state.cashUSD, 800);
}
console.log('6) coherencia temporal (antedatación inválida rechazada, posterior válida): OK');

// 7) R3: doc con createdAt FUTURO (reloj atrás) — la compra con el mismo
// executedAt se ordena ANTES por (executedAt, createdAt, _id) y se rechaza
// con rollback real: sin fill y sin bump de versión.
login('rs-user-f');
const T2 = NOW - 100_000;
await model.ManualDemoTrade.collection.insertOne({
    userId: 'rs-user-f', clientOrderId: oid(), kind: 'fx', symbol: 'EURUSD', name: 'FX semilla',
    contract: null, side: 'buy', openClose: 'open', fxFrom: 'EUR', fxTo: 'USD', quantity: 1000,
    status: 'filled', fillPrice: 1.2, currency: 'EUR', fee: 0, fillSource: 'manual-simulado',
    executedAt: new Date(T2), rejectReason: null,
    createdAt: new Date(NOW + 3_600_000), updatedAt: new Date(NOW + 3_600_000), // futuro, sin pasar por timestamps de Mongoose
});
const fut = await actions.placeManualOrder(buy('ASTS', 10, 40, { currency: 'USD', executedAt: T2 }));
assert.ok(fut.ok);
if (fut.ok) assert.equal(fut.outcome, 'rejected', `createdAt futuro: ${JSON.stringify(fut)}`);
const docsF = await model.ManualDemoTrade.countDocuments({ userId: 'rs-user-f' });
const fillsF = await model.ManualDemoTrade.countDocuments({ userId: 'rs-user-f', status: 'filled' });
assert.equal(docsF, 2, `docs F: ${docsF} (semilla + rechazo, sin fill)`);
assert.equal(fillsF, 1, `fills F: ${fillsF} (solo la semilla)`);
const accDocF = await model.ManualDemoAccount.findOne({ userId: 'rs-user-f' });
assert.equal(accDocF?.version, 0, `version F: ${accDocF?.version} (sin fill confirmado)`);
console.log('7) createdAt futuro: rechazo con rollback real (sin fill, version 0): OK');

// 8) Empate exacto real (executedAt y createdAt): desempate por _id de la BD.
login('rs-user-g');
const TIE = new Date(NOW - 200_000);
const raw = (side: string, price: number, hex: string) => ({
    _id: new mongoose.Types.ObjectId(hex),
    userId: 'rs-user-g', clientOrderId: oid(), kind: 'accion', symbol: 'G.MC', name: 'G.MC',
    contract: null, side, openClose: 'open', fxFrom: null, fxTo: null, quantity: 10,
    status: 'filled', fillPrice: price, currency: 'EUR', fee: 0, fillSource: 'manual-simulado',
    executedAt: TIE, rejectReason: null, createdAt: TIE, updatedAt: TIE,
});
await model.ManualDemoTrade.collection.insertOne(raw('buy', 10, 'ffffffffffffffffffffffff'));
await model.ManualDemoTrade.collection.insertOne(raw('sell', 12, 'aaaaaaaaaaaaaaaaaaaaaaaa'));
// _id aa < ff: la venta se ordena ANTES → se total-rechaza sin posición y la
// compra queda (posición 10). Vender 5 ahora solo cuadra con ese orden.
const tie = await actions.placeManualOrder(sell('G.MC', 5, 12));
assert.ok(tie.ok);
if (tie.ok) {
    assert.equal(tie.outcome, 'filled', `empate exacto: ${JSON.stringify(tie)}`);
    assert.equal(tie.state.positions[0]?.quantity, 5);
}
console.log('8) empate exacto (executedAt, createdAt): desempate por _id real: OK');

// 9) Venta ANTEDATADA con comisión que sobregira el cash en su fecha:
// el replay (accounting.ts) la rechaza aunque el cash ACTUAL la cubra.
login('rs-user-h');
await actions.placeManualOrder(buy('H.MC', 20, 10, { executedAt: NOW - 300_000 }));           // cash 99.800
await actions.placeManualOrder(sell('H.MC', 10, 5000, { executedAt: NOW - 100_000 }));         // cash 149.800
const feeBack = await actions.placeManualOrder(sell('H.MC', 10, 100, { fee: 150000, executedAt: NOW - 200_000 }));
assert.ok(feeBack.ok);
if (feeBack.ok) assert.equal(feeBack.outcome, 'rejected', `fee antedatada: ${JSON.stringify(feeBack)}`);
const docsH = await model.ManualDemoTrade.countDocuments({ userId: 'rs-user-h', status: 'filled' });
assert.equal(docsH, 2, `fills H: ${docsH} (la venta con fee no entra)`);
const accDocH = await model.ManualDemoAccount.findOne({ userId: 'rs-user-h' });
assert.equal(accDocH?.version, 2, `version H: ${accDocH?.version}`);
assert.equal(accDocH?.cashEUR, 149_800, `cash H: ${accDocH?.cashEUR}`);
console.log('9) venta antedatada con comisión en sobregiro: rechazada por el replay (sin fill, caché intacta): OK');

await mongoose.disconnect();
await rs.stop();
console.log('REAL-RS 9/9: todas las pruebas pasaron (transacciones reales usadas en cada escritura)');
