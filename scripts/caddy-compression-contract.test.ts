import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('VM delegates response compression to Caddy instead of Node', () => {
    const config = readFileSync(new URL('../next.config.ts', import.meta.url), 'utf8');
    assert.match(config, /compress:\s*false/);
    assert.doesNotMatch(config, /compress:\s*true/);
    const caddy = readFileSync(new URL('../infra/caddy/Caddyfile', import.meta.url), 'utf8');
    assert.match(caddy, /encode\s+(?:zstd\s+gzip|gzip\s+zstd)/);
});
