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
    // Comments document the measured reallocation; they are not YAML values.
    return block.slice(deploy).split('\n').filter((line) => !line.trimStart().startsWith('#')).join('\n');
}

test('production backend and default worker preserve measured CPU caps and memory', () => {
    assert.match(limits('backend'), /limits:\s*\n\s*cpus: "2\.00"\s*\n\s*memory: 1472M/);
    // Worker default: 4G desde 2026-10-31 (3G eran el suelo con 1 hilo; el
    // salto a 4 hilos I/O-bound se midio con CPU 0,17 % y 8.709 pendientes).
    assert.match(limits('worker'), /limits:\s*\n\s*cpus: "1\.00"\s*\n\s*memory: 4G/);
    // Carril dedicado de prices (frescura intradia 15 min sin el backlog de default).
    assert.match(limits('worker-prices'), /limits:\s*\n\s*cpus: "0\.50"\s*\n\s*memory: 512M/);
});

test('default worker does not overlap evidence scans', () => {
    // El solape de escaneos pesados lo impide la coalescencia de encolado
    // (#3677: una copia en vuelo por job); los hilos extra (defecto 4,
    // medido I/O-bound: CPU 0,17 % con 8.709 pendientes) solo paralelizan
    // esperas HTTP. prices va en su propio carril (worker-prices).
    assert.ok(source.includes('"--threads", "${WORKER_THREADS:-4}", "-Q", "default"'));
    assert.ok(!source.includes('"-Q", "default", "prices"'), 'prices fuera del carril default');
});

function assertGlobalMemoryBudget(compose: string): void {
    const memory = [...compose.matchAll(/^          memory: ([0-9]+)([MG])$/gm)];
    assert.ok(memory.length >= 20, 'all production service limits must be counted');
    const total = memory.reduce((sum, match) => sum + Number(match[1]) * (match[2] === 'G' ? 1024 : 1), 0);
    assert.ok(total <= 16384, `stack memory ${total} MiB exceeds 16384 MiB`);
}

test('backend reallocation preserves global memory budget and rejects old 2G', () => {
    assertGlobalMemoryBudget(source);
    const mutant = source.replace('memory: 1472M', 'memory: 2G');
    assert.notEqual(mutant, source, 'negative control must mutate backend limit');
    assert.throws(() => assertGlobalMemoryBudget(mutant), /stack memory 16704 MiB exceeds 16384 MiB/);
});
