/**
 * sectionErrorKey: el usuario ve un mensaje generico por categoria (resuelto
 * con t() desde ui.sectionError.*), nunca el error crudo (URLs, rutas
 * internas, fragments de respuesta).
 * Ejecucion: node --experimental-strip-types --test scripts/section-error.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { sectionErrorKey } from '../lib/section-error.ts';

const dict = JSON.parse(readFileSync('lib/i18n/messages/es/ui.json', 'utf8')).sectionError;

describe('sectionErrorKey', () => {
    it('no expone el mensaje crudo del error', () => {
        const raw = 'GET https://api.internal.example/v1/quotes?token=SECRET failed with 502 Bad Gateway: {"trace":"abc"}';
        const key = sectionErrorKey(new Error(raw));
        assert.ok(key.startsWith('ui.sectionError.'));
        const shown = dict[key.slice('ui.sectionError.'.length)];
        assert.ok(!shown.includes('api.internal.example'));
        assert.ok(!shown.includes('SECRET'));
        assert.ok(!shown.includes('trace'));
    });
    it('categoriza fallos de red', () => {
        assert.equal(sectionErrorKey(new Error('fetch failed')), 'ui.sectionError.network');
        assert.equal(sectionErrorKey(new Error('ECONNREFUSED')), 'ui.sectionError.network');
        assert.equal(sectionErrorKey(new Error('request timeout')), 'ui.sectionError.network');
        assert.match(dict.network, /conectar/);
    });
    it('categoriza sesion caducada', () => {
        assert.equal(sectionErrorKey(new Error('401 Unauthorized')), 'ui.sectionError.session');
        assert.equal(sectionErrorKey(new Error('403 forbidden')), 'ui.sectionError.session');
        assert.match(dict.session, /sesi.n/);
    });
    it('categoriza fallos del servicio', () => {
        assert.equal(sectionErrorKey(new Error('502 Bad Gateway')), 'ui.sectionError.server');
        assert.equal(sectionErrorKey(new Error('Internal Server Error')), 'ui.sectionError.server');
        assert.match(dict.server, /servicio ha fallado/);
    });
    it('cae al mensaje generico ante errores no Error o desconocidos', () => {
        assert.equal(sectionErrorKey('boom'), 'ui.sectionError.generic');
        assert.equal(sectionErrorKey(new Error('something odd')), 'ui.sectionError.generic');
        assert.equal(sectionErrorKey(undefined), 'ui.sectionError.generic');
        assert.match(dict.generic, /No se pudieron cargar/);
    });
});
