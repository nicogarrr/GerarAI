/**
 * Modulo Inversores (PR 1): copy honesto y nav. Sin datos no se inventan cifras,
 * Daily Journal no es "cartera de Munger" y el valor sale en dolares compactos.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: explicit extension for node strip-types.
import { form13fValueToUsd } from '../lib/form13f-value.ts';
const ES_INVESTORS_JSON = readFileSync('lib/i18n/messages/es/investors.json', 'utf8');

const grid = (readFileSync('app/(root)/inversores/page.tsx', 'utf8') + ES_INVESTORS_JSON);
// Carteras se fusiona en /inversores (decision de Nico, WhatsApp 2026-10-20 00:59):
// las aserciones sobre la pagina de carteras apuntan ahora al hub que la absorbe.
const portfolios = (readFileSync('app/(root)/inversores/page.tsx', 'utf8') + ES_INVESTORS_JSON);
const detail = readFileSync('app/(root)/inversores/[slug]/page.tsx', 'utf8');
const format = readFileSync('app/(root)/inversores/_components/format.ts', 'utf8');
const constants = readFileSync('lib/constants.ts', 'utf8');

test('sin 13F no implica cero ni ausencia de participaciones documentadas', () => {
    assert.match(grid, /Sin 13F · ver ficha/);
    assert.match(detail, /getInvestorPortfolio\(slug\)/);
    assert.match(readFileSync('app/(root)/inversores/_components/Portfolio.tsx', 'utf8'), /SIN_DATOS/);
});

test('la fuente y limitaciones permanecen en tarjetas y cartera etiquetada', () => {
    for (const source of [grid, portfolios]) {
        assert.match(source, /SEC, Form 13F \(EDGAR\)/);
        assert.match(source, /45 días/);
    }
    assert.match(readFileSync('app/(root)/inversores/_components/Portfolio.tsx', 'utf8'), /portfolio.limitations/);
});

test('el <value> del 13F va en dolares desde 2023: Apple 200237120 son 200,2 M, no miles', () => {
    // 13F-HR de Berkshire (acc. 0001193125-26-352200, 30-06-2026): 692.000 acciones de Apple.
    assert.equal(form13fValueToUsd(200237120, '2026-06-30'), 200237120);
    assert.equal(form13fValueToUsd(200237120, '2022-12-31'), 200237120);
});

test('los informes anteriores a 2023 siguen en miles y se pasan a dolares', () => {
    assert.equal(form13fValueToUsd(200237, '2022-09-30'), 200237000);
    assert.equal(form13fValueToUsd(null, '2026-06-30'), null);
    assert.equal(form13fValueToUsd(1, null), null);
});

test('las paginas pasan la fecha del informe y no multiplican por mil a ciegas', () => {
    assert.match(format, /form13fValueToUsd\(raw, reportDate\)/);
    assert.ok(!/thousands \* 1000/.test(format));
    assert.ok(!/thousands \* 1000/.test(readFileSync('app/(root)/ownership/page.tsx', 'utf8')));
});

test('ninguna pagina etiqueta una cartera como cartera de Munger', () => {
    for (const source of [grid, portfolios, detail]) {
        assert.ok(!/cartera de Munger/i.test(source));
    }
});

test('la ficha no muestra tickers (el 13F solo trae CUSIP y emisor)', () => {
    assert.ok(!/\.ticker|\.symbol/.test(detail));
});

test('Inversores tiene entrada de nav una sola vez', () => {
    const tree = constants.slice(constants.indexOf('export const NAV_SECTIONS'), constants.indexOf('export function flattenNavItems'));
    assert.equal(tree.split("href: '/inversores'").length - 1, 1);
});
