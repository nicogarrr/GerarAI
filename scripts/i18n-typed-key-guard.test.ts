/**
 * Guard del accessor i18n: `t()` NO puede volver a aceptar una clave que no
 * sea una hoja de `es.json`.
 *
 * Por qué: `lib/i18n/t.ts` exportaba DOS overloads, el segundo con
 * `path: string`. TypeScript resuelve la llamada contra el último overload
 * viable, así que `TranslationKey` (derivada de `typeof es`) quedaba sin
 * efecto: un typo como `t('portaflio.total')` compilaba y en producción
 * pintaba la clave cruda en pantalla. El repo creía estar protegido y por eso
 * `check-i18n.mjs` rastrea las claves a mano con 146 líneas de regex.
 *
 * El segundo fallo era peor: `Leaves<T>` devolvía el NOMBRE de la hoja
 * (`"library"`) y no la ruta (`"knowledge.library"`), así que ninguna clave con
 * punto era asignable ni siquiera al overload bueno.
 *
 * También comprueba que el fichero no vuelva a llevar texto corrupto: una API
 * de next-intl que se come la frase circundante ("para" + "TranslatedMessage").
 *
 * Ejecución: node --experimental-strip-types --test scripts/i18n-typed-key-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { loadMessages } from './i18n-messages.mjs';

const t = readFileSync('lib/i18n/t.ts', 'utf8');
const es = loadMessages('es').dict as unknown;

/** `para[A-Z]` pegado a un nombre de API: texto al que una librería se tragó la frase. */
const SWALLOWED_API_NAME = /\bpara[A-Z][A-Za-z]{3,}/;

/** Recorre el diccionario y devuelve sus claves con punto ("knowledge.library"). */
function dottedKeys(node: unknown, prefix = ''): string[] {
    if (node === null || typeof node !== 'object') return [];
    return Object.entries(node as Record<string, unknown>).flatMap(([key, value]) => {
        const path = prefix ? `${prefix}.${key}` : key;
        return typeof value === 'string' ? [path] : dottedKeys(value, path);
    });
}

describe('i18n: la clave de t() está realmente tipada', () => {
    it('t() declara path como TranslationKey y solo como TranslationKey', () => {
        const params = [...t.matchAll(/export\s+function\s+t\s*\(([^)]*)\)/g)].map((match) => match[1]);

        assert.equal(params.length, 1, `se esperaba 1 sola firma de t(), hay ${params.length}`);
        assert.match(
            params[0],
            /^path:\s*TranslationKey\s*,/,
            't() debe aceptar únicamente TranslationKey: un `path: string` ensancha el parámetro y anula el tipado',
        );
        assert.doesNotMatch(
            params[0],
            /:\s*string/,
            'ningún parámetro de t() puede ser `string`: reabre la puerta a claves no verificables',
        );
    });

    it('t() tiene una única declaración, sin overloads sueltos', () => {
        const declarations = t.match(/export\s+function\s+t\s*\(/g) ?? [];

        assert.equal(
            declarations.length,
            1,
            'los overloads eligen el último, así que basta uno extra con `path: string` para perder el tipado',
        );
    });

    it('Leaves construye rutas con punto, no nombres de hoja sueltos', () => {
        assert.match(
            t,
            /`\$\{K\}\.\$\{Leaves</,
            'Leaves debe prefijar el namespace: sin el prefijo, "knowledge.library" no es asignable',
        );
        assert.doesNotMatch(
            t,
            /extends\s+string\s*\?\s*K\s*:\s*Leaves</,
            'la recursión no puede devolver `Leaves` pelado: eso produce "library", no "knowledge.library"',
        );
    });

    it('TranslationKey se sigue derivando del diccionario real', () => {
        assert.match(
            t,
            /type\s+TranslationKey\s*=\s*Leaves<\s*typeof es\s*>/,
            'si TranslationKey deja de derivar de `typeof es` se desvincula del contenido de es.json',
        );
        assert.ok(
            dottedKeys(es).length > 0,
            'es.json vacío o mal formado: la derivación de TranslationKey no tiene de qué colgarse',
        );
    });

    it('el módulo no lleva texto corrupto por una API de next-intl', () => {
        const hit = t.match(SWALLOWED_API_NAME);

        assert.equal(
            hit?.[0],
            undefined,
            `"${hit?.[0] ?? ''}" es texto al que una API se le tragó la frase; reescríbelo en español`,
        );
        assert.match(t, /NextIntlClientProvider/, 'la mención real a la API de next-intl va entre backticks');
    });
});