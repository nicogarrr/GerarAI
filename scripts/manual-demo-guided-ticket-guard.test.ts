/**
 * Guarda del ticket guiado de la demo manual (Nico, 21-oct-2026: registro
 * «mucho más guiado», tipo IBKR): el símbolo/subyacente se busca y se elige
 * en vez de escribirse a mano, sin romper la honestidad del ticket.
 *
 * Ejecución: node --experimental-strip-types --test scripts/manual-demo-guided-ticket-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const ticket = readFileSync('components/paper-trading/OrderTicket.tsx', 'utf8');

describe('ticket demo guiado (buscador de instrumento)', () => {
    it('usa el TickerSearchInput compartido para símbolo/subyacente', () => {
        assert.match(ticket, /import \{ TickerSearchInput \} from '@\/components\/search\/TickerSearchInput'/);
        assert.match(ticket, /<TickerSearchInput/);
        assert.match(ticket, /onSelect=\{onSelectInstrument\}/);
    });

    it('la selección rellena símbolo y nombre con la identidad real del resultado', () => {
        assert.match(ticket, /function onSelectInstrument\(stock: StockWithWatchlistStatus\)/);
        assert.match(ticket, /setSymbol\(stock\.symbol\)/);
        assert.match(ticket, /setName\(stock\.name\)/);
    });

    it('la divisa NUNCA se preselecciona desde el buscador (exchange no prueba divisa)', () => {
        // La exchange del resultado puede venir inferida del search del
        // proveedor, no solo del listado CNMV: ningun preset es seguro.
        assert.doesNotMatch(ticket, /setCurrency\('EUR'\)|setCurrency\('USD'\)/);
        assert.doesNotMatch(ticket, /stock\.exchange === 'BME'|exchange === 'NASDAQ'|exchange === 'NYSE'/);
        // El toggle manual sigue intacto.
        assert.match(ticket, /onClick=\{\(\) => setCurrency\(value\)\}/);
    });

    it('editar el símbolo tras elegir limpia el nombre autocompletado (no registra A con nombre de B)', () => {
        assert.match(ticket, /function onSymbolFieldChange\(value: string\)/);
        assert.match(ticket, /onValueChange=\{onSymbolFieldChange\}/);
        // La limpieza solo actua cuando el valor se aparta de la seleccion.
        assert.match(ticket, /selectedSymbol\.current !== null && value !== selectedSymbol\.current/);
        assert.match(ticket, /selectedSymbol\.current = null;\s*setName\(''\)/);
        // La seleccion marca el simbolo elegido y rellena identidad.
        assert.match(ticket, /selectedSymbol\.current = stock\.symbol/);
    });

    it('sigue siendo presentacional: nada de servidor dentro del ticket', () => {
        assert.doesNotMatch(ticket, /mongoose|manual-demo\.model|lib\/actions\//);
    });

    it('el copy ya no afirma que no hay buscador y la ayuda explica el guiado', () => {
        assert.doesNotMatch(ticket, /no hay buscador en la fase manual/);
        assert.match(ticket, /Busca por nombre o ticker y elige/);
    });

    it('las fechas nativas llevan la mitigación de desborde móvil (min-w-0/texto reducido; verificación visual iOS pendiente en QA)', () => {
        const fechaEjecucion = ticket.match(/id=\{`\$\{uid\}-executed`\}[\s\S]{0,400}/)?.[0] ?? '';
        const bloqueInput = ticket.match(/<Input\s+className="[^"]*min-w-0[^"]*"\s+id=\{`\$\{uid\}-executed`\}/);
        assert.ok(bloqueInput, 'el datetime-local lleva min-w-0/max-w-full y texto reducido');
        assert.match(fechaEjecucion, /datetime-local/);
    });

    it('la identidad del contrato de opción sigue manual y etiquetada (sin cadena fabricada)', () => {
        assert.match(ticket, /Fecha del contrato; no implica que hoy sea negociable/);
        assert.doesNotMatch(ticket, /optionChain|cadena de contratos|strikesDisponibles/i);
    });

    it('mantiene la advertencia de fill manual (no ejecución de mercado)', () => {
        assert.match(ticket, /no es una ejecución de\s+mercado/i);
    });
});
