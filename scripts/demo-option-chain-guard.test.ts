/**
 * Guarda del selector guiado de contrato de opción (cadena CBOE diferida):
 * la fuente gratuita verificable ya existe (delayed quotes de CBOE), así que
 * el ticket ofrece vencimientos/strikes reales SIN romper la honestidad:
 * la prima diferida es referencia etiquetada, nunca precio actual, y la vía
 * manual queda intacta.
 *
 * Ejecución: node --experimental-strip-types --test scripts/demo-option-chain-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const action = readFileSync('lib/actions/demo-option-chain.actions.ts', 'utf8');
const ticket = readFileSync('components/paper-trading/OrderTicket.tsx', 'utf8');
const view = readFileSync('lib/paper-trading/option-chain-view.ts', 'utf8');
const sharedCache = readFileSync('lib/market/cboe-chain-cache.ts', 'utf8');
const valuation = readFileSync('lib/actions/manual-demo.actions.ts', 'utf8');
const es = JSON.parse(readFileSync('lib/i18n/messages/es/paperTrading.json', 'utf8'));

describe('selector guiado de contrato (cadena CBOE diferida)', () => {
    it('la acción exige sesión y valida el símbolo antes de consultar la fuente', () => {
        assert.match(action, /requireAuthenticatedUser/);
        assert.match(action, /SYMBOL_RE/);
        assert.match(action, /reason: 'invalidSymbol'/);
    });

    it('la respuesta lleva SOLO identidad + última operación: nunca bid/ask/mid', () => {
        assert.doesNotMatch(action, /\b(?:bid|ask|mid)\s*:/i);
        assert.match(view, /export type DemoOptionChainTrade = \{ price: number; time: string \}/);
    });

    it('valoración y selector comparten UNA caché de cadenas (la fuente no se duplica)', () => {
        assert.match(sharedCache, /export const sharedCboeChainCache = createCboeChainCache\(\)/);
        assert.match(valuation, /import \{ sharedCboeChainCache \} from '@\/lib\/market\/cboe-chain-cache'/);
        assert.doesNotMatch(valuation, /createCboeChainCache\(\)/);
    });

    it('el ticket etiqueta el dato como diferido y nunca autorrellena el precio desde la cadena', () => {
        assert.match(ticket, /paperTrading\.ticket\.chainHint/);
        assert.match(ticket, /paperTrading\.ticket\.chainRefTrade/);
        assert.doesNotMatch(ticket, /setPrice\([^)]*chain/);
    });

    it('la vía manual (strike y vencimiento escritos a mano) sigue disponible', () => {
        assert.match(ticket, /id=\{`\$\{uid\}-strike`\}/);
        assert.match(ticket, /id=\{`\$\{uid\}-expiry`\}/);
        assert.match(ticket, /paperTrading\.ticket\.expiryHint/);
    });

    it('los textos en español enmarcan la muestra diferida y los fracasos honestos', () => {
        assert.match(es.ticket.chainHint, /diferida al menos 15 min/);
        assert.match(es.ticket.chainRefTrade, /\{price\} USD · \{time\} \(Nueva York\)/);
        assert.match(es.ticket.chainRefTrade, /no precio actual/);
        for (const reason of ['invalidSymbol', 'notCovered', 'sourceUnavailable', 'saturated', 'noAuth']) {
            assert.ok(es.ticket.chainError[reason], `falta chainError.${reason}`);
        }
        assert.match(es.ticket.chainError['notCovered'], /escribe el contrato a mano/);
    });

    it('avisa si el contrato no está en la muestra consultada, sin bloquearlo ni juzgar con otra cadena', () => {
        assert.match(ticket, /chain\.underlying === symbol\.trim\(\)\.toUpperCase\(\)/);
        assert.match(ticket, /paperTrading\.ticket\.chainNotListed/);
        assert.match(es.ticket.chainNotListed, /muestra consultada/);
        // Es un aviso informativo, nunca un error de validación que bloquee.
        assert.match(ticket, /text-amber-400\"\>\{ti\('paperTrading\.ticket\.chainNotListed'\)/);
    });

    it('la edad de la cadena consultada queda etiquetada (fetchedAt de la fuente)', () => {
        assert.match(ticket, /paperTrading\.ticket\.chainFetchedAt/);
        assert.match(es.ticket.chainFetchedAt, /\{time\}/);
    });

    it('presencia POR TIPO: ausente = no listado, null = listado sin trade; el selector filtra por callPut', () => {
        assert.match(view, /call\?: DemoOptionChainTrade \| null;/);
        assert.match(view, /put\?: DemoOptionChainTrade \| null;/);
        // La acción NO inicializa lados en null: solo pone el lado que trae la fuente.
        assert.match(action, /row = \{ strike \};/);
        assert.doesNotMatch(action, /\{ strike, call: null, put: null \}/);
        // La UI filtra los strikes por el tipo elegido y valida con presencia.
        assert.match(ticket, /r\[callPut\] !== undefined/);
        assert.match(ticket, /sideRow === undefined/);
    });

    it('una resolución obsoleta (símbolo cambiado en vuelo) se descarta: secuencia + correspondencia en render', () => {
        // Editar/elegir símbolo invalida la secuencia de la petición en vuelo.
        assert.match(ticket, /chainSeq\.current \+= 1;/);
        assert.match(ticket, /const seq = \+\+chainSeq\.current;/);
        // Ok, error y finally se descartan si la secuencia ya no es la vigente.
        const staleGuards = ticket.match(/seq !== chainSeq\.current/g) ?? [];
        assert.ok(staleGuards.length >= 2, 'faltan descartes de resoluciones obsoletas');
        assert.match(ticket, /if \(seq === chainSeq\.current\) setChainLoading\(false\);/);
        // El render exige correspondencia símbolo-cadena, no solo chain !== null.
        assert.match(ticket, /\{chain && chainCoversSymbol \? \(/);
    });

    it('el fracaso de la fuente no rompe el ticket: hay estado de error explícito', () => {
        assert.match(ticket, /setChainError\(chainErrorMessage\(ti, result\.reason\)\)/);
        assert.match(ticket, /setChainError\(ti\('paperTrading\.ticket\.chainError\.sourceUnavailable'\)\)/);
    });
});
