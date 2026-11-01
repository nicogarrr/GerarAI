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
        // i18n: la pista vive en el diccionario (ticket.searchHint).
        assert.match(ticket, /paperTrading\.ticket\.searchHint/);
    });

    it('la fecha lleva contención reforzada: fila propia + overflow-hidden (fallo real iPhone 21-oct-2026; verificación en dispositivo pendiente)', () => {
        const fechaEjecucion = ticket.match(/id=\{`\$\{uid\}-executed`\}[\s\S]{0,400}/)?.[0] ?? '';
        const bloqueInput = ticket.match(/<Input\s+style=\{\{ minHeight: 44 \}\}\s+className="[^"]*min-w-0[^"]*"\s+id=\{`\$\{uid\}-executed`\}/);
        assert.ok(bloqueInput, 'el datetime-local lleva min-w-0/max-w-full y texto reducido');
        assert.match(fechaEjecucion, /datetime-local/);
        // min-w-0/max-w-full no bastaron en iOS Safari: barrera dura de
        // recorte y sin grid multi-columna en la fila.
        assert.match(ticket, /<div className="w-full overflow-hidden">/);
        assert.doesNotMatch(ticket, /col-span-2 space-y-1\.5">\s*<Label htmlFor=\{`\$\{uid\}-executed`\}/);
    });

    it('sin campo de comisión en el ticket (Nico 21-oct-2026): 0 simulado, libro y fills históricos intactos', () => {
        // Ni input ni label de comisión ni validación de un input inexistente.
        assert.doesNotMatch(ticket, /Comisión \(\{currency\}\)/);
        assert.doesNotMatch(ticket, /setFee\(/);
        // Fee fija 0 SIMULADA con etiqueta honesta: no es tarifa de bróker
        // ni afirmación de operar gratis; el envío conserva el campo fee del
        // libro (contrato intacto).
        assert.match(ticket, /const parsedFee = 0;/);
        // i18n: el aviso vive en el diccionario (ticket.manualNote).
        assert.match(ticket, /paperTrading\.ticket\.manualNote/);
        const dict = JSON.parse(readFileSync('lib/i18n/messages/es/paperTrading.json', 'utf8'));
        assert.match(dict.ticket.manualNote, /Sin comisión en la demo \(0 simulado\): no reproduce la tarifa de ningún bróker/);
        assert.match(ticket, /fee: parsedFee/);
        assert.doesNotMatch(ticket, /tarifa de IBKR|IBKR gratis|comisiones de Interactive Brokers/i);
    });

    it('el label de cantidad no envuelve: unidad como sufijo del campo (QA píxeles 21-oct-2026)', () => {
        // «Cantidad (contratos)» envolvía a 2 líneas a 390px y se pegaba al
        // borde del input. Label corto + sufijo dentro del campo relativo.
        assert.match(ticket, /<Label htmlFor=\{`\$\{uid\}-quantity`\}>\{ti\('paperTrading\.ticket\.quantity'\)\}<\/Label>/);
        assert.doesNotMatch(ticket, /Cantidad \(\{kindLabel\}\)<\/Label>/);
        assert.match(ticket, /pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-gray-500">\{kindLabel\}<\/span>/);
        // El sufijo queda asociado al input (auditor 21-oct-2026).
        assert.match(ticket, /aria-describedby=\{`\$\{uid\}-quantity-unit`\}/);
        assert.match(ticket, /<span id=\{`\$\{uid\}-quantity-unit`\} className="pointer-events-none/);
    });

    it('placeholder del nombre neutro: no parece un valor relleno', () => {
        assert.match(ticket, /placeholder=\{ti\('paperTrading\.ticket\.namePh'\)\}/);
        assert.doesNotMatch(ticket, /placeholder="p\. ej\. AST SpaceMobile"/);
    });

    it('la lista del buscador abre hacia abajo en el ticket (captura iPhone 21-oct-2026)', () => {
        assert.match(ticket, /dropdownSide="bottom"/);
        const search = readFileSync('components/search/TickerSearchInput.tsx', 'utf8');
        // Dirección fija = sin volteo de Radix y tope 40dvh (visual viewport
        // con teclado), con scroll propio; sin la prop, comportamiento previo.
        assert.match(search, /side=\{dropdownSide\}/);
        assert.match(search, /avoidCollisions=\{dropdownSide === undefined\}/);
        assert.match(search, /max-h-\[min\(15rem,40dvh\)\]/);
        // El tope fijo no basta: con el teclado abierto la lista puede quedar
        // bajo él. La altura se mide con geometría pura (components/search/
        // list-fit.ts, con tests de comportamiento en ticker-search-list-fit):
        // NUNCA supera el espacio real (suelo 0, sin mínimos mágicos), pide
        // UN solo reposicionamiento por apertura (guardia scrolledForSpace,
        // reseteada al cerrar) y se re-mide con los eventos del visual
        // viewport (resize/scroll = teclado, offset, barras) con cleanup.
        assert.match(search, /computeListFit\(spaceBelow, scrolledForSpace\.current\)/);
        assert.match(search, /scrollIntoView\(\{ block: 'center' \}\)/);
        assert.match(search, /window\.visualViewport/);
        assert.match(search, /scrolledForSpace\.current = true/);
        assert.match(search, /vv\?\.addEventListener\('resize', measureBelowInput\)/);
        assert.match(search, /vv\?\.addEventListener\('scroll', measureBelowInput\)/);
        assert.match(search, /vv\?\.removeEventListener\('resize', measureBelowInput\)/);
        assert.match(search, /if \(!open\) \{\s*scrolledForSpace\.current = false;/);
        assert.match(search, /style=\{dropdownSide \? listMaxHeightStyle\(listMaxHeight\) : undefined\}/);
        // Cierre limpio si el scroll de página deja el input fuera del
        // pliegue (lista abierta no flota offscreen); nunca dirección arriba.
        assert.match(search, /inputAboveViewport\(rect\.bottom/);
        assert.doesNotMatch(search, /side="top"/);
        // El comportamiento de la geometría se prueba con espacios reales.
        assert.match(readFileSync('scripts/ticker-search-list-fit.test.ts', 'utf8'), /computeListFit\(0, true\)/);
    });

    it('los mensajes de estado del buscador se anuncian a lectores de pantalla', () => {
        const search = readFileSync('components/search/TickerSearchInput.tsx', 'utf8');
        // QA de formularios (21-oct-2026): «Sin resultados» y «No se pudo
        // buscar» eran <p> sin role ni aria-live — invisibles para AT.
        assert.match(search, /<p role="alert" className="mt-1 text-xs text-red-400">/);
        assert.match(search, /<p role="status" aria-live="polite" className="mt-1 text-sm text-gray-500">\{ti\('search\.noResultsFor'/);
    });

    it('la identidad del contrato de opción sigue manual y etiquetada (sin cadena fabricada)', () => {
        // i18n: la nota vive en el diccionario (ticket.expiryHint).
        assert.match(ticket, /paperTrading\.ticket\.expiryHint/);
        assert.doesNotMatch(ticket, /optionChain|cadena de contratos|strikesDisponibles/i);
    });

    it('mantiene la advertencia de fill manual (no ejecución de mercado)', () => {
        // i18n: la advertencia vive en el diccionario (ticket.manualNote).
        assert.match(ticket, /paperTrading\.ticket\.manualNote/);
    });

    it('resumen de coste previo visible, calculado solo con los datos del usuario', () => {
        // Bloque propio (no la frase enterrada en la nota pequeña).
        // i18n: el título vive en el diccionario (ticket.summaryTitle).
        assert.match(ticket, /paperTrading\.ticket\.summaryTitle/);
        assert.doesNotMatch(ticket, /Importe estimado/);
        // Desglose: lado, cantidad, precio, multiplicador de opción y comisión con signo según lado.
        assert.match(ticket, /\{sideLabel\} · \{f\.formatNumber\(parsedQuantity\)\} \{kindLabel\}/);
        assert.match(ticket, /paperTrading\.ticket\.multiplierPart/);
        assert.match(ticket, /side === 'buy' \? '\+' : '−'/);
        // Etiqueta honesta según lado y sin presentarlo como cotización.
        // i18n: los rótulos viven en el diccionario (ticket.costBuy/costSell).
        assert.match(ticket, /paperTrading\.ticket\.costBuy/);
        assert.match(ticket, /paperTrading\.ticket\.costSell/);
        assert.match(ticket, /paperTrading\.ticket\.summaryDisclaimer/);
        // La comisión ya no es input (0 simulada fija): el resumen no la
        // muestra (condición > 0) y el total la suma como 0. Cantidad y
        // precio inválidos siguen SIN resumen.
        assert.match(ticket, /\{parsedFee > 0 \? ti\('paperTrading\.ticket\.feePart', \{ sign: side === 'buy' \? '\+' : '−'/);
        assert.match(ticket, /total \+ parsedFee : total - parsedFee/);
        // Cantidad/precio ya tenían validación equivalente en el mismo useMemo.
        assert.match(ticket, /!Number\.isInteger\(parsedQuantity\) \|\| parsedQuantity <= 0\) return null/);
        assert.match(ticket, /!Number\.isFinite\(parsedPrice\) \|\| parsedPrice <= 0\) return null/);
        // Sin red: el bloque no consulta cotización (sigue presentacional).
        assert.doesNotMatch(ticket, /quote|markPrice|refreshValuation/i);
    });
});
