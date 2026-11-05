import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// Access logs de Caddy para medir latencia por request (5-nov-2026: cola de
// red de /watchlist). Condiciones de seguridad del encargo: nada de
// credenciales en el log y tamaño acotado para no llenar el disco.
const caddy = readFileSync(new URL('../infra/caddy/Caddyfile', import.meta.url), 'utf8');
const compose = readFileSync(new URL('../docker-compose.prod.yml', import.meta.url), 'utf8');

test('el frontend de la VM escribe access logs JSON filtrados', () => {
    assert.match(caddy, /log \{/);
    assert.match(caddy, /format filter \{/);
    assert.match(caddy, /wrap json/);
});

test('el log borra las cabeceras con credenciales (además del REDACTED por defecto de Caddy >= 2.5)', () => {
    for (const field of [
        'request>headers>Cookie',
        'request>headers>Authorization',
        'request>headers>Proxy-Authorization',
        'resp_headers>Set-Cookie',
    ]) {
        assert.match(caddy, new RegExp(field.replace(/[>]/g, '\\s*>\\s*') + '\\s+delete'), `falta borrar ${field}`);
    }
});

test('el log elimina los parámetros de query que suelen llevar secretos', () => {
    assert.match(caddy, /request>uri query \{/);
    for (const param of ['token', 'api_key', 'apikey', 'key', 'signature', 'code', 'secret', 'password']) {
        assert.match(caddy, new RegExp(`delete ${param}\\b`), `falta delete ${param}`);
    }
});

test('el tamaño del log queda acotado por la rotación de Docker (json-file 10m x 3)', () => {
    const start = compose.indexOf('\n  caddy:');
    assert.ok(start > 0, 'servicio caddy no encontrado');
    const rest = compose.slice(start + 1);
    const next = rest.search(/\n  [a-z][a-z0-9-]*:/);
    const block = next < 0 ? rest : rest.slice(0, next);
    assert.ok(block.includes('logging: *default-logging'), 'caddy sin el ancla de rotación de logs');
    assert.match(compose, /x-default-logging: &default-logging\n  driver: json-file\n  options:\n    max-size: "10m"\n    max-file: "3"/);
});
