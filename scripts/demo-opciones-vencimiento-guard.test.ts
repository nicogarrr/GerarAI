/**
 * Guarda de los avisos de vencimiento de opciones en la demo (21-oct-2026).
 *
 * Invariantes:
 * - El estado de vencimiento se calcula con la fecha civil del contrato en
 *   NUEVA YORK (zona de los vencimientos OCC), nunca con la tz del usuario.
 * - El servidor etiqueta (badge informativo); el libro NO ejerce, NO expira
 *   y NO liquida posiciones automáticamente, ni muta cash por vencimiento.
 * - El ticket rechaza ejecutar una opción después de su vencimiento con la
 *   MISMA regla del servidor (buildOptionFill/expirationState), comparando
 *   contra la fecha de ejecución: la historia anterior al vencimiento sí
 *   se puede registrar.
 *
 * Ejecución: node --experimental-strip-types --test scripts/demo-opciones-vencimiento-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { expiryBadge, isRealDate, newYorkDate } from '../lib/paper-trading/options.ts';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { parseOptionKey, instrumentKey } from '../lib/paper-trading/types.ts';

describe('expiryBadge: la zona es Nueva York, no la del usuario', () => {
    // 2026-10-21T02:30:00Z = 2026-10-20 22:30 en Nueva York (EDT, UTC-4):
    // la fecha civil NY es 20 aunque en Madrid ya sea 21.
    const nowMs = Date.parse('2026-10-21T02:30:00Z');
    it('newYorkDate confirma el caso límite usado', () => {
        assert.equal(newYorkDate(nowMs), '2026-10-20');
    });
    it('vencida / vence-hoy / vigente contra la fecha civil NY', () => {
        assert.equal(expiryBadge('2026-10-19', nowMs), 'vencida');
        assert.equal(expiryBadge('2026-10-20', nowMs), 'vence-hoy');
        assert.equal(expiryBadge('2026-10-21', nowMs), 'vigente');
    });
    it('isRealDate rechaza fechas con forma pero imposibles', () => {
        assert.equal(isRealDate('2026-02-30'), false);
        assert.equal(isRealDate('2026-13-01'), false);
        assert.equal(isRealDate('2026-10-20'), true);
    });
});

describe('parseOptionKey: identidad del contrato desde la instrumentKey', () => {
    it('round-trip con instrumentKey y rechazos de fase 1', () => {
        const contract = { underlying: 'asts', callPut: 'call' as const, strike: 30, expiry: '2026-09-18', multiplier: 100, deliverable: 'acciones' as const, adjusted: false };
        assert.deepEqual(parseOptionKey(instrumentKey({ kind: 'opcion', contract, name: 'ASTS 2026-09-18 30 Call' })), {
            underlying: 'ASTS', expiry: '2026-09-18', callPut: 'call', strike: 30, multiplier: 100,
        });
        assert.equal(parseOptionKey('ASTS'), null);
        assert.equal(parseOptionKey('O:ASTS:2026-09-18:call:30:50'), null); // multiplicador no fase 1
        assert.equal(parseOptionKey('O:ASTS:2026-09-18:call:0:100'), null);
        assert.equal(parseOptionKey('O:ASTS:18-09-2026:call:30:100'), null);
    });
});

describe('wiring servidor/UI y honestidad (sin autoejercicio)', () => {
    const actions = readFileSync('lib/actions/manual-demo.actions.ts', 'utf8');
    const ticket = readFileSync('components/paper-trading/OrderTicket.tsx', 'utf8');
    const table = readFileSync('components/paper-trading/PositionsTable.tsx', 'utf8');
    const submit = readFileSync('components/paper-trading/submit.ts', 'utf8');

    it('el servidor etiqueta cada posición de opción (expiry + badge NY)', () => {
        assert.match(actions, /import \{ buildOptionFill, expiryBadge \} from '@\/lib\/paper-trading\/options'/);
        assert.match(actions, /optionBadge: option \? expiryBadge\(option\.expiry, Date\.now\(\)\) : null/);
        assert.match(actions, /optionExpiry: option\?\.expiry \?\? null/);
        assert.match(submit, /optionBadge: 'vigente' \| 'vence-hoy' \| 'vencida' \| null/);
    });

    it('el ticket rechaza ejecutar tras el vencimiento con la regla del servidor', () => {
        assert.match(ticket, /import \{ expirationState, isRealDate \} from '@\/lib\/paper-trading\/options'/);
        // i18n: el mensaje vive en el diccionario (ticket.errors.expiredContract).
        assert.match(ticket, /paperTrading\.ticket\.errors\.expiredContract/);
        assert.match(ticket, /isRealDate\(expiry\)/);
    });

    it('los badges se muestran y declaran que el libro NO ejerce ni expira solo', () => {
        // i18n: el badge vive en el diccionario (positions.expiredBadge).
        assert.match(table, /paperTrading\.positions\.expiredBadge/);
        assert.match(table, /paperTrading\.positions\.expiredDetail/);
        // Copy honesto (auditor 21-oct-2026): la API rechaza fechas
        // posteriores al vencimiento y precio 0, así que NO se puede prometer
        // «liquidación a mano» de una opción vencida. El badge indica el
        // cierre con fecha real (≤ vencimiento) y declara la limitación.


        assert.doesNotMatch(table, /el cierre o la liquidación se registran a mano/);
        // Sin párrafo permanente (QA píxeles 21-oct-2026): etiqueta corta +
        // detalle expandible nativo (details/summary, seguro en móvil).
        assert.match(table, /expiredBadge', \{ date: formatContractDate\(position\.optionExpiry, locale\) \}\)\}\s*<\/span>/);
        // Contenedor de bloque válido (details/p no pueden ir dentro de span).
        assert.match(table, /<div className="mt-1">\s*<span className="inline-block rounded border border-amber-800/);
        assert.doesNotMatch(table, /<span className="mt-1 block">\s*<span className="inline-block rounded border border-amber-800/);
        assert.match(table, /<details className="mt-1 text-xs text-gray-400">/);
        assert.match(table, /<summary className="[^"]*">\{ti\('paperTrading\.positions\.whatMeans'\)\}<\/summary>/);
        // Sin lógica de cierre/liquidación automática por vencimiento.
        assert.doesNotMatch(actions, /autoejerc|asignaci[oó]n autom[aá]tica|closeExpired|expirePosition|liquidaci[oó]n autom[aá]tica/i);
    });

    it('la fecha del contrato se formatea como civil, sin crear Date (tz-safe)', () => {
        assert.match(table, /function formatContractDate\(iso: string, locale: string = 'es'\): string/);
        assert.doesNotMatch(table, /new Date\(position\.optionExpiry\)/);
    });
});
