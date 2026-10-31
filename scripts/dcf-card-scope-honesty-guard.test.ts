/**
 * Guarda F65: la tarjeta «Oportunidades por valor intrínseco» probaba solo 6
 * candidatas del screener y declaraba alcance de universo («Todo el universo
 * del screener», «Ninguna empresa del universo supera hoy un 5 %…»), y un DCF
 * fallido contaba como «sin potencial». Ahora el alcance real se calcula
 * (probadas/evaluadas/fallidas) y la tarjeta lo declara.
 *
 * Los tests ejercitan el helper real (lib/overview/dcf-candidates.ts) y
 * comprueban que el componente lo usa, no solo strings sueltas.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
    DCF_MIN_UPSIDE_PCT,
    dcfEmptyNote,
    dcfScopeNote,
    summarizeDcfProbe,
    // @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
} from '../lib/overview/dcf-candidates.ts';


/** t() de test: resuelve las claves home.dcf.* contra messages/es/home.json
 *  con interpolación {var}, para que el guard siga comprobando el copy real
 *  que se renderiza, no una copia congelada en el test. */
const ES_HOME = JSON.parse(readFileSync('lib/i18n/messages/es/home.json', 'utf8'));
const t = (key: string, vars: Record<string, string | number> = {}): string => {
    const value = key.split('.').slice(1).reduce<unknown>((node, part) => (node as Record<string, unknown>)[part], ES_HOME);
    assert.equal(typeof value, 'string', `falta ${key} en messages/es/home.json`);
    return (value as string).replace(/\{(\w+)\}/g, (_, name) => String(vars[name] ?? `{${name}}`));
};

const COMPONENT = 'components/PersonalizedOverview.tsx';

void test('el resumen de la sonda cuenta probadas, evaluadas y fallidas de verdad', () => {
    const scope = summarizeDcfProbe([
        { evaluated: true, opportunity: { symbol: 'A' } },
        { evaluated: true, opportunity: null },
        { evaluated: false, opportunity: null },
    ]);
    assert.deepEqual(scope, { probed: 3, evaluated: 2, failed: 1 });
    assert.deepEqual(summarizeDcfProbe([]), { probed: 0, evaluated: 0, failed: 0 });
});

void test('el estado vacío distingue «evaluadas sin potencial» de «no evaluables»', () => {
    assert.equal(
        dcfEmptyNote(t, { probed: 6, evaluated: 4, failed: 2 }),
        `Ninguna de las 4 candidatas del screener evaluadas supera hoy un ${DCF_MIN_UPSIDE_PCT} % de potencial sobre su valor intrínseco; 2 no se pudieron evaluar.`,
        'con evaluadas: el alcance son las candidatas, nunca el universo, y las fallidas se declaran',
    );
    assert.equal(
        dcfEmptyNote(t, { probed: 4, evaluated: 4, failed: 0 }),
        `Ninguna de las 4 candidatas del screener evaluadas supera hoy un ${DCF_MIN_UPSIDE_PCT} % de potencial sobre su valor intrínseco.`,
        'sin fallidas no se añade coletilla',
    );
    assert.equal(
        dcfEmptyNote(t, { probed: 6, evaluated: 0, failed: 6 }),
        'No se pudo calcular el valor intrínseco de las 6 candidatas del screener probadas.',
        'sin ninguna evaluada no cabe concluir nada sobre el potencial',
    );
    assert.equal(
        dcfEmptyNote(t, { probed: 0, evaluated: 0, failed: 0 }),
        'El screener no devolvió candidatas sobre las que calcular el valor intrínseco.',
    );
    for (const scope of [{ probed: 6, evaluated: 4, failed: 2 }, { probed: 6, evaluated: 0, failed: 6 }, { probed: 0, evaluated: 0, failed: 0 }]) {
        assert.ok(!dcfEmptyNote(t, scope).includes('universo'), 'ningún estado vacío habla en nombre del universo');
    }
});

void test('la nota de alcance declara las candidatas probadas y las no evaluables', () => {
    assert.equal(
        dcfScopeNote(t, { probed: 6, evaluated: 6, failed: 0 }, '10B'),
        'Las 6 primeras candidatas del screener (market cap > 10B), sin filtro de sector.',
    );
    assert.equal(
        dcfScopeNote(t, { probed: 6, evaluated: 4, failed: 2 }, '10B'),
        'Las 6 primeras candidatas del screener (market cap > 10B), sin filtro de sector; 2 no se pudieron evaluar.',
    );
});

void test('el componente prueba con tope declarado y usa los textos del helper', () => {
    const source = `${readFileSync(COMPONENT, 'utf8')}\n${readFileSync('lib/actions/home-overview.actions.ts', 'utf8')}`;
    assert.match(source, /candidateLimit: DCF_CANDIDATE_LIMIT[\s\S]*\.slice\(0, params\.candidateLimit\)/, 'el tope de candidatas es la constante declarada');
    assert.match(source, /upside > DCF_MIN_UPSIDE_PCT/, 'el umbral es la constante declarada');
    assert.match(source, /summarizeDcfProbe\(results\)/, 'el alcance se calcula de la sonda real');
    assert.match(source, /\{dcfScopeNote\(\s*t,/, 'el encabezado declara el alcance real');
    assert.ok(!source.includes('{dcfEmptyNote('), 'sin candidatas la tarjeta no se pinta: no hay estado vacío');
    assert.ok(!source.includes('Ninguna empresa del universo'), 'desaparece la conclusión categórica sobre el universo');
    assert.ok(!source.includes('Todo el universo del screener'), 'desaparece el alcance de universo en el encabezado');
});

void test('un DCF fallido no cuenta como «sin potencial»', () => {
    const source = `${readFileSync(COMPONENT, 'utf8')}\n${readFileSync('lib/actions/home-overview.actions.ts', 'utf8')}`;
    assert.match(source, /evaluated: false, opportunity: null/, 'los fallos se marcan como no evaluados');
    assert.match(source, /evaluated: true,[\s\S]*?opportunity: upside > DCF_MIN_UPSIDE_PCT/, 'solo las evaluadas pueden dar oportunidad');
});

void test('las candidatas con fundamentales persistidos se prueban primero', () => {
    // QA inicio DCF: sin fundamentales persistidos el DCF no es calculable y
    // la tarjeta quedaba «0 de 6 calculables». La sonda prioriza las filas del
    // screener con has_fundamentals y el contador declara las no evaluables.
    const source = readFileSync('lib/actions/home-overview.actions.ts', 'utf8');
    assert.match(source, /screener\.filter\(\(row\) => row\.has_fundamentals\)/, 'se separan las candidatas con fundamentales');
    assert.match(source, /\[\.\.\.withFundamentals, \.\.\.withoutFundamentals\]\.slice\(0, params\.candidateLimit\)/, 'las con fundamentales entran antes en la sonda');
});
