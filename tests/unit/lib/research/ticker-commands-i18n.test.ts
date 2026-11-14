import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { TICKER_COMMANDS } from '@/lib/research/ticker-commands';

/**
 * Las etiquetas visibles de los comandos de ficha viven en los diccionarios
 * (search.command.labels.*); el código del comando (DES/FA/...) es neutro.
 * Antes el texto español estaba hardcodeado en lib/research/ticker-commands.ts
 * y el buscador lo pintaba igual con English activado.
 */
const esSearch = JSON.parse(readFileSync('lib/i18n/messages/es/search.json', 'utf8'));
const enSearch = JSON.parse(readFileSync('lib/i18n/messages/en/search.json', 'utf8'));

const lookup = (dict: unknown, labelKey: string): unknown =>
    labelKey
        .split('.')
        .slice(1) // el primer segmento es el area (search)
        .reduce<unknown>((node, key) => (node && typeof node === 'object' ? (node as Record<string, unknown>)[key] : undefined), dict);

describe('etiquetas i18n de los comandos de ficha', () => {
    it('cada comando lleva labelKey bajo search.command.labels', () => {
        for (const command of TICKER_COMMANDS) {
            expect(command.labelKey, command.code).toBe(`search.command.labels.${command.code.toLowerCase()}`);
        }
    });

    it('cada labelKey existe en los diccionarios ES y EN', () => {
        for (const command of TICKER_COMMANDS) {
            expect(typeof lookup(esSearch, command.labelKey), `es ${command.code}`).toBe('string');
            expect(typeof lookup(enSearch, command.labelKey), `en ${command.code}`).toBe('string');
        }
    });

    it('el texto visible ES no cambia', () => {
        const visible = Object.fromEntries(TICKER_COMMANDS.map((c) => [c.code, lookup(esSearch, c.labelKey)]));
        expect(visible).toEqual({
            DES: 'Visión general',
            FA: 'Financieros',
            HDS: 'Propietarios, 13F e insiders',
            N: 'Noticias',
            GP: 'Gráfico',
            TESIS: 'Tesis',
            ALERT: 'Alertas',
        });
    });

    it('el texto EN está traducido', () => {
        const visible = Object.fromEntries(TICKER_COMMANDS.map((c) => [c.code, lookup(enSearch, c.labelKey)]));
        expect(visible).toEqual({
            DES: 'Overview',
            FA: 'Financials',
            HDS: 'Holders, 13F & insiders',
            N: 'News',
            GP: 'Chart',
            TESIS: 'Thesis',
            ALERT: 'Alerts',
        });
    });
});
