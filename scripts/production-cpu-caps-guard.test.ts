import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync('docker-compose.prod.yml', 'utf8');
function limits(service: string): string {
    const match = new RegExp(`^  ${service}:\\n([\\s\\S]*?)(?=^  [a-z][\\w-]*:|$)`, 'm').exec(source);
    assert.ok(match, `production service ${service} must exist`);
    return match[1].slice(match[1].indexOf('    deploy:'));
}

test('production backend and default worker preserve measured CPU caps and memory', () => {
    assert.match(limits('backend'), /limits:\s*\n\s*cpus: "2\.00"\s*\n\s*memory: 2G/);
    assert.match(limits('worker'), /limits:\s*\n\s*cpus: "1\.00"\s*\n\s*memory: 1280M/);
});
