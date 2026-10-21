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

    it('la divisa solo se preselecciona con identidad verificada (BME/CNMV), nunca inferida', () => {
        assert.match(ticket, /stock\.exchange === 'BME'\) setCurrency\('EUR'\)/);
        // Sin heurísticas de divisa por nombre de bolsa o ticker.
        assert.doesNotMatch(ticket, /exchange === 'NASDAQ'|exchange === 'NYSE'|setCurrency\('USD'\)/);
    });

    it('sigue siendo presentacional: nada de servidor dentro del ticket', () => {
        assert.doesNotMatch(ticket, /mongoose|manual-demo\.model|lib\/actions\//);
    });

    it('el copy ya no afirma que no hay buscador y la ayuda explica el guiado', () => {
        assert.doesNotMatch(ticket, /no hay buscador en la fase manual/);
        assert.match(ticket, /Busca por nombre o ticker y elige/);
    });

    it('las fechas nativas no desbordan en móvil (iOS no recorta date/datetime-local)', () => {
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
