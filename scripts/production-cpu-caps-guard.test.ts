import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync('docker-compose.prod.yml', 'utf8');
function limits(service: string): string {
    const start = source.indexOf(`\n  ${service}:\n`);
    assert.ok(start >= 0, `production service ${service} must exist`);
    const rest = source.slice(start + 1);
    const nextService = /\n  [a-z][\w-]*:/.exec(rest);
    const block = nextService ? rest.slice(0, nextService.index) : rest;
    const deploy = block.indexOf('    deploy:');
    assert.ok(deploy >= 0, 'deploy resource limits must exist');
    return block.slice(deploy);
}

test('production backend and default worker preserve measured CPU caps and memory', () => {
    assert.match(limits('backend'), /limits:\s*\n\s*cpus: "2\.00"\s*\n\s*memory: 2G/);
    assert.match(limits('worker'), /limits:\s*\n\s*cpus: "1\.00"\s*\n\s*memory: 3G/);
});

test('default worker does not overlap evidence scans', () => {
    assert.ok(source.includes('"--threads", "1", "-Q", "default", "prices"'));
});
