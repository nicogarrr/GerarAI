import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { parseTickerCommand, TICKER_COMMANDS } from '../lib/research/ticker-commands.ts';

describe('comandos de ficha tipo terminal (ASTS FA)', () => {
    it('cubren las 7 funciones pedidas', () => {
        assert.deepEqual(
            TICKER_COMMANDS.map((c) => c.code),
            ['DES', 'FA', 'HDS', 'N', 'GP', 'TESIS', 'ALERT'],
        );
    });
    it('cada comando apunta a una ruta real', () => {
        assert.equal(TICKER_COMMANDS.find((c) => c.code === 'DES')!.href('ASTS'), '/research/ASTS');
        assert.equal(TICKER_COMMANDS.find((c) => c.code === 'FA')!.href('ASTS'), '/research/ASTS?view=financials');
        assert.equal(TICKER_COMMANDS.find((c) => c.code === 'HDS')!.href('ASTS'), '/research/ASTS?view=holders');
        assert.equal(TICKER_COMMANDS.find((c) => c.code === 'N')!.href('ASTS'), '/research/news?ticker=ASTS');
        assert.equal(TICKER_COMMANDS.find((c) => c.code === 'GP')!.href('ASTS'), '/research/ASTS#grafico');
        assert.equal(TICKER_COMMANDS.find((c) => c.code === 'TESIS')!.href('ASTS'), '/research/ASTS/tesis');
        assert.equal(TICKER_COMMANDS.find((c) => c.code === 'ALERT')!.href('ASTS'), '/alerts?symbol=ASTS');
    });
    it('el ticker se escapa en la ruta (BRK.B y tickers con mercado)', () => {
        assert.equal(TICKER_COMMANDS.find((c) => c.code === 'FA')!.href('BRK.B'), '/research/BRK.B?view=financials');
        assert.equal(TICKER_COMMANDS.find((c) => c.code === 'N')!.href('SAN.MC'), '/research/news?ticker=SAN.MC');
    });
    it('reconoce comando exacto en cualquier capitalización', () => {
        for (const raw of ['ASTS FA', 'asts fa', 'Asts Fa', '  ASTS   FA  ']) {
            const parsed = parseTickerCommand(raw);
            assert.equal(parsed?.ticker, 'ASTS', raw);
            assert.equal(parsed?.exact?.code, 'FA', raw);
        }
    });
    it('prefijo parcial sugiere sin fijar comando exacto', () => {
        const parsed = parseTickerCommand('ASTS F');
        assert.equal(parsed?.exact, null);
        assert.deepEqual(parsed?.matches.map((c) => c.code), ['FA']);
        const several = parseTickerCommand('ASTS T');
        assert.deepEqual(several?.matches.map((c) => c.code), ['TESIS']);
        const all = parseTickerCommand('ASTS ');
        assert.equal(all?.matches.length, TICKER_COMMANDS.length);
    });
    it('un ticker solo NO es comando: la búsqueda normal sigue intacta', () => {
        assert.equal(parseTickerCommand('ASTS'), null);
        assert.equal(parseTickerCommand(''), null);
        assert.equal(parseTickerCommand('apple'), null);
        assert.equal(parseTickerCommand('ASTS ZZ'), null);
        assert.equal(parseTickerCommand('ASTS FA EXTRA'), null);
    });
    it('los códigos no son prefijos ambiguos entre sí salvo coincidencia real', () => {
        for (const cmd of TICKER_COMMANDS) {
            const parsed = parseTickerCommand(`ASTS ${cmd.code}`);
            assert.equal(parsed?.exact?.code, cmd.code, cmd.code);
        }
    });
});

describe('integración en el buscador Ctrl+K', () => {
    const search = readFileSync('components/SearchCommand.tsx', 'utf8') + readFileSync('components/SearchCommandDialog.tsx', 'utf8');
    it('parsea el input y ofrece los comandos', () => {
        assert.ok(search.includes("import { parseTickerCommand } from \"@/lib/research/ticker-commands\""));
        assert.ok(search.includes('parseTickerCommand(searchTerm)'));
        assert.ok(search.includes('value={`cmd:${exactCommand.command.code}`}'));
        assert.ok(search.includes('value={`cmd:${cmd.code}`}'));
    });
    it('con comando exacto el comando es el primer resultado (Enter lo abre, #1518)', () => {
        assert.ok(search.includes("value:selectedValue || (exactCommand ? `cmd:${exactCommand.command.code}`"));
        // la búsqueda de acciones no pisa la selección cuando hay comando exacto
        assert.ok(search.includes('if (!parseTickerCommand(query.trim())?.exact) {'));
    });
    it('el comando exacto no depende del proveedor: se pinta antes del estado de carga/error', () => {
        assert.ok(search.indexOf('heading="Comando"') < search.indexOf('searchError ? ('));
    });
    it('los resultados de acciones siguen participando en la selección', () => {
        assert.ok(search.includes('value={`stock:${stock.symbol}`}'));
        assert.ok(search.includes('setSelectedValue(result.stocks[0]'));
    });
    it('con comando tecleado no se pinta «Sin resultados» aunque no haya acciones (QA 21-oct: «asts fa»)', () => {
        assert.ok(search.includes('displayStocks?.length === 0 && !commandQuery'));
    });
});

describe('anclas en la ficha', () => {
    // `#alerta` ya NO es destino del comando ALERT (ahora /alerts?symbol=);
    // queda para enlaces directos y su retirada/limpieza del comentario en
    // page.tsx espera la reserva de esa ficha con pilot.
    const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
    it('#grafico envuelve la cotización de cabecera y #alerta el botón de alerta', () => {
        assert.ok(page.includes('id="grafico"'));
        assert.ok(page.includes('id="alerta"'));
        assert.ok(page.indexOf('id="grafico"') < page.indexOf('<CompanyHeaderQuote'));
        assert.ok(page.indexOf('id="alerta"') < page.indexOf('<QuickAlertButton'));
    });
});
