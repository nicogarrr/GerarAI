/**
 * Guard de rendimiento: el menú del selector de país (cmdk) no puede viajar
 * en el bundle inicial de /sign-up (página pública de entrada). El gatillo
 * queda eager y el menú carga diferido al abrir el desplegable.
 *
 * Ejecución: node --experimental-strip-types --test scripts/country-select-lazy-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const field = readFileSync('components/forms/CountrySelectField.tsx', 'utf8');
const menu = readFileSync('components/forms/CountrySelectCommand.tsx', 'utf8');

describe('selector de país: menú cmdk diferido', () => {
    it('el campo no importa ui/command ni cmdk en estático', () => {
        assert.ok(!/from\s+['"]@\/components\/ui\/command['"]/.test(field), 'CountrySelectField no debe importar ui/command');
        assert.ok(!/from\s+['"]cmdk['"]/.test(field), 'CountrySelectField no debe importar cmdk');
        assert.match(field, /dynamic\(\(\) => import\('@\/components\/forms\/CountrySelectCommand'\)/);
    });

    it('el menú vive en su propio componente con la búsqueda y las opciones', () => {
        assert.match(menu, /^'use client';/m);
        assert.match(menu, /from\s+'@\/components\/ui\/command'/);
        const esAuth = JSON.parse(readFileSync('lib/i18n/messages/es/auth.json', 'utf8'));
        assert.equal(esAuth.signUp.countrySearchPlaceholder, 'Buscar países…', 'placeholder del buscador en el diccionario ES');
        assert.ok(menu.includes("t('auth.signUp.countrySearchPlaceholder')"), 'el menú consume la clave i18n');
        assert.match(menu, /country-select-item/);
    });

    it('el gatillo precarga el chunk antes del click', () => {
        assert.match(field, /onPointerDown=\{preloadCountryCommand\}/);
        assert.match(field, /onFocus=\{preloadCountryCommand\}/);
    });

    it('seleccionar un país cierra el desplegable (comportamiento conservado)', () => {
        assert.match(field, /onSelect=\{\(next\) => \{/);
        assert.match(field, /setOpen\(false\)/);
    });
});
