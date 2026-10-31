/**
 * Guard F300-extensión: la tarjeta de alerta del inicio es navegable ENTERA
 * con el patrón de enlace estirado: UN solo enlace primario estirado
 * (after:absolute after:inset-0 sobre la tarjeta relative), el CTA
 * secundario por encima (relative z-10) con su propio destino, sin enlaces
 * anidados ni roles duplicados. El destino principal lo decide
 * alertCardDestination: investigación del ticker > documento fuente > no
 * navegable.
 * Ejecución: node --experimental-strip-types --test scripts/alerts-card-stretched-link-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { alertCardDestination, alertThesisHref } from '../lib/alerts/card-destination.ts';

void test('el destino principal prioriza la investigación del ticker', () => {
    assert.deepEqual(
        alertCardDestination({ ticker: 'AAPL', sourceUrl: 'https://sec.gov/x' }),
        { href: '/research/AAPL?view=thesis', external: false },
    );
    assert.deepEqual(
        alertCardDestination({ ticker: null, sourceUrl: 'https://sec.gov/x' }),
        { href: 'https://sec.gov/x', external: true },
    );
    assert.equal(alertCardDestination({ ticker: null, sourceUrl: null }), null);
    assert.equal(alertCardDestination({}), null);
});

void test('la tarjeta estira exactamente un enlace y protege el secundario', () => {
    const source: string = readFileSync(new URL('../components/PersonalizedOverview.tsx', import.meta.url), 'utf8');
    const cardsStart = source.indexOf('triggeredAlerts.map');
    assert.ok(cardsStart > -1);
    const cardsEnd = source.indexOf('})}', source.indexOf('</article>', cardsStart));
    const block = source.slice(cardsStart, cardsEnd);

    // Tarjeta clickable: relative + affordance de hover solo cuando hay destino.
    assert.match(block, /alertCardDestination\(item\)/);
    assert.match(block, /destination \? 'relative border-gray-700\/50 bg-gray-900\/50 transition-colors hover:border-teal-700\/60 hover:bg-gray-900'/);

    // El enlace de investigación (siempre interno) va estirado.
    const researchLink = block.slice(block.indexOf('home.alerts.reviewThesis') - 400, block.indexOf('home.alerts.reviewThesis'));
    assert.match(researchLink, /after:absolute after:inset-0/);

    // El documento fuente va estirado SOLO cuando no hay ticker (es entonces
    // el destino principal); con ticker queda por encima como secundario.
    assert.match(block, /item\.ticker \? 'relative z-10' : "after:absolute after:inset-0/);

    // Sin roles ni handlers que dupliquen la navegación del enlace real.
    assert.ok(!block.includes('role="link"'), 'sin role=link duplicado: el enlace estirado ya es el control');
    assert.ok(!block.includes('onClick'), 'sin onClick de navegación: el enlace estirado basta');
});

console.log('alerts-card-stretched-link-guard: ok');

void test('varias clases de acciones ("LEN, LEN.B") enlazan a la primera ficha, sin coma ni espacio', () => {
    assert.equal(alertThesisHref('LEN, LEN.B'), '/research/LEN?view=thesis');
    assert.equal(alertThesisHref('BRK.B'), '/research/BRK.B?view=thesis');
    assert.deepEqual(
        alertCardDestination({ ticker: 'LEN, LEN.B', sourceUrl: null }),
        { href: '/research/LEN?view=thesis', external: false },
    );
});
