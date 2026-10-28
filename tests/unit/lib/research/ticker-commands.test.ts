import { describe, expect, it } from 'vitest';
import { TICKER_COMMANDS, parseTickerCommand } from '@/lib/research/ticker-commands';

describe('parseTickerCommand', () => {
    it('ticker + código exacto', () => {
        const r = parseTickerCommand('aapl des');
        expect(r?.ticker).toBe('AAPL');
        expect(r?.exact?.code).toBe('DES');
    });
    it('prefijo parcial lista coincidencias sin exacta', () => {
        const r = parseTickerCommand('MSFT T');
        expect(r?.matches.map((m) => m.code)).toEqual(['TESIS']);
        expect(r?.exact).toBeNull();
    });
    it('ticker con espacio y sin prefijo muestra todos los comandos, sin exacta', () => {
        const r = parseTickerCommand('NVDA ');
        expect(r?.matches).toHaveLength(TICKER_COMMANDS.length);
        expect(r?.exact).toBeNull();
    });
    it('no es comando: sin espacio, prefijo sin coincidencias, o ticker inválido', () => {
        expect(parseTickerCommand('AAPL')).toBeNull();
        expect(parseTickerCommand('AAPL zzz')).toBeNull();
        expect(parseTickerCommand('1AAPL des')).toBeNull();
        expect(parseTickerCommand('AAPL des extra')).toBeNull();
        expect(parseTickerCommand('A'.repeat(13) + ' des')).toBeNull();
    });
    it('acepta tickers con punto y guion (BRK.B)', () => {
        expect(parseTickerCommand('brk.b fa')?.ticker).toBe('BRK.B');
        expect(parseTickerCommand('rds-a n')?.exact?.code).toBe('N');
    });
});

describe('href de comandos', () => {
    it('codifica el ticker para que no rompa la URL', () => {
        const des = TICKER_COMMANDS.find((c) => c.code === 'DES')!;
        expect(des.href('BRK.B')).toBe('/research/BRK.B');
        expect(des.href('A/B?x')).toBe('/research/A%2FB%3Fx');
        expect(TICKER_COMMANDS.find((c) => c.code === 'ALERT')!.href('X&Y')).toBe('/alerts?symbol=X%26Y');
        expect(TICKER_COMMANDS.find((c) => c.code === 'N')!.href('X')).toBe('/research/news?ticker=X');
    });
});

describe('todas las rutas de comandos', () => {
    it('cada comando lleva a su pantalla', () => {
        expect(Object.fromEntries(TICKER_COMMANDS.map((c) => [c.code, c.href('X')]))).toEqual({
            DES: '/research/X',
            FA: '/research/X?view=financials',
            HDS: '/research/X?view=holders',
            N: '/research/news?ticker=X',
            GP: '/research/X#grafico',
            TESIS: '/research/X/tesis',
            ALERT: '/alerts?symbol=X',
        });
    });
});
