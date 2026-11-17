/**
 * Puerta de npm audit (scripts/npm-audit-gate.mjs): la excepcion de
 * GHSA-fc5q-39xc-vjpf deja pasar SOLO esa advisory.
 *   node --test scripts/npm-audit-gate.test.mjs
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';
import { chmodSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { IGNORED_ADVISORIES, evaluateAudit, npmAuditJson } from './npm-audit-gate.mjs';

const PICOMATCH = {
  source: 1247710, name: 'picomatch', dependency: 'picomatch',
  title: 'picomatch vulnerable to ReDoS through single-branch repeated extglobs',
  url: 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf', severity: 'high', range: '<=4.0.7',
};
const OTHER = {
  source: 999, name: 'left-pad', dependency: 'left-pad', title: 'otra advisory',
  url: 'https://github.com/advisories/GHSA-aaaa-bbbb-cccc', severity: 'high', range: '<1.3.1',
};

/** Forma real de `npm audit --json`: raiz con objeto en via, cadena con strings. */
function report(...roots) {
  const vulnerabilities = {};
  for (const adv of roots) {
    vulnerabilities[adv.name] = { name: adv.name, severity: adv.severity, via: [adv] };
    vulnerabilities[`dep-de-${adv.name}`] = { name: `dep-de-${adv.name}`, severity: adv.severity, via: [adv.name] };
  }
  return { auditReportVersion: 2, vulnerabilities };
}

test('la excepcion esta limitada a una sola advisory, la de picomatch', () => {
  assert.deepEqual([...IGNORED_ADVISORIES], ['GHSA-fc5q-39xc-vjpf']);
});

test('solo la advisory de picomatch: pasa y la declara como ignorada', () => {
  const res = evaluateAudit(report(PICOMATCH));
  assert.equal(res.ok, true);
  assert.deepEqual(res.blocking, []);
  assert.deepEqual(res.ignored, ['ghsa-fc5q-39xc-vjpf']);
});

test('otra advisory high sola: sigue fallando y se nombra', () => {
  const res = evaluateAudit(report(OTHER));
  assert.equal(res.ok, false);
  assert.deepEqual(res.blocking.map((b) => b.name), ['left-pad']);
  assert.deepEqual(res.ignored, []);
});

test('picomatch mas otra advisory: falla solo por la otra', () => {
  const res = evaluateAudit(report(PICOMATCH, OTHER));
  assert.equal(res.ok, false);
  assert.deepEqual(res.blocking.map((b) => b.name), ['left-pad']);
  assert.deepEqual(res.ignored, ['ghsa-fc5q-39xc-vjpf']);
});

test('una advisory critical distinta falla; una moderate distinta no bloquea (como --audit-level=high)', () => {
  assert.equal(evaluateAudit(report({ ...OTHER, severity: 'critical' })).ok, false);
  assert.equal(evaluateAudit(report({ ...OTHER, severity: 'moderate' })).ok, true);
});

test('un id parecido pero distinto no hereda la excepcion', () => {
  const lookalike = { ...PICOMATCH, url: 'https://github.com/advisories/GHSA-fc5q-39xc-vjpg' };
  assert.equal(evaluateAudit(report(lookalike)).ok, false);
});

test('paquete high sin advisory atribuible bloquea', () => {
  const res = evaluateAudit({ vulnerabilities: { raro: { name: 'raro', severity: 'high', via: [] } } });
  assert.equal(res.ok, false);
});

test('falla cerrado: entradas invalidas o error de npm no pasan', () => {
  assert.equal(evaluateAudit(null).ok, false);
  assert.equal(evaluateAudit({}).ok, false);
  assert.equal(evaluateAudit({ error: { code: 'ENOAUDIT', summary: 'registro caido' } }).ok, false);
  assert.match(evaluateAudit({ error: { summary: 'registro caido' } }).error, /registro caido/);
});

test('arbol sin vulnerabilidades pasa', () => {
  assert.equal(evaluateAudit({ vulnerabilities: {} }).ok, true);
});

test('la misma advisory vista en dos paquetes se lista una sola vez', () => {
  const res = evaluateAudit({
    vulnerabilities: {
      a: { name: 'a', severity: 'high', via: [OTHER] },
      b: { name: 'b', severity: 'high', via: [OTHER] },
    },
  });
  assert.equal(res.ok, false);
  assert.equal(res.blocking.length, 1);
});

test('cadena via hacia un paquete inexistente (grafo incompleto) bloquea', () => {
  const res = evaluateAudit({ vulnerabilities: { a: { name: 'a', severity: 'high', via: ['fantasma'] } } });
  assert.equal(res.ok, false);
  assert.deepEqual(res.blocking.map((b) => b.name), ['a']);
});

test('cadena con una rama rota bloquea aunque otra rama llegue a la advisory ignorada', () => {
  const res = evaluateAudit({
    vulnerabilities: {
      a: { name: 'a', severity: 'high', via: ['picomatch', 'fantasma'] },
      picomatch: { name: 'picomatch', severity: 'high', via: [PICOMATCH] },
    },
  });
  assert.equal(res.ok, false);
  assert.deepEqual(res.blocking.map((b) => b.name), ['a']);
});

test('ciclo sin advisory raiz bloquea; ciclo con salida a la advisory ignorada pasa', () => {
  const sinRaiz = evaluateAudit({
    vulnerabilities: {
      a: { name: 'a', severity: 'high', via: ['b'] },
      b: { name: 'b', severity: 'high', via: ['a'] },
    },
  });
  assert.equal(sinRaiz.ok, false);
  const conSalida = evaluateAudit({
    vulnerabilities: {
      a: { name: 'a', severity: 'high', via: ['b'] },
      b: { name: 'b', severity: 'high', via: ['a', 'picomatch'] },
      picomatch: { name: 'picomatch', severity: 'high', via: [PICOMATCH] },
    },
  });
  assert.equal(conSalida.ok, true);
  assert.deepEqual(conSalida.ignored, ['ghsa-fc5q-39xc-vjpf']);
});

test('cadena larga resuelta hasta la raiz ignorada: pasa; hasta una ajena: falla por la ajena', () => {
  const chain = (root) => ({
    vulnerabilities: {
      vitest: { name: 'vitest', severity: 'high', via: ['vite'] },
      vite: { name: 'vite', severity: 'high', via: ['tinyglobby'] },
      tinyglobby: { name: 'tinyglobby', severity: 'high', via: [root.name] },
      [root.name]: { name: root.name, severity: 'high', via: [root] },
    },
  });
  assert.equal(evaluateAudit(chain(PICOMATCH)).ok, true);
  const bad = evaluateAudit(chain(OTHER));
  assert.equal(bad.ok, false);
  assert.deepEqual(bad.blocking.map((b) => b.name), ['left-pad']);
});

test('nombre de paquete tipo prototipo (constructor) no cuenta como paquete del informe', () => {
  const res = evaluateAudit({ vulnerabilities: { a: { name: 'a', severity: 'high', via: ['constructor'] } } });
  assert.equal(res.ok, false);
});

test('npmAuditJson: devuelve el stdout aunque npm salga con 1; error de spawn o sin stdout da texto vacio', () => {
  const calls = [];
  const spawn = (cmd, args, opts) => {
    calls.push({ cmd, args, opts });
    return { status: 1, stdout: '{"vulnerabilities":{}}' };
  };
  assert.equal(npmAuditJson(['--omit=dev'], spawn), '{"vulnerabilities":{}}');
  assert.equal(calls[0].cmd, 'npm');
  assert.deepEqual(calls[0].args, ['audit', '--json', '--omit=dev']);
  assert.equal(npmAuditJson([], () => ({ error: new Error('ENOENT'), stdout: 'x' })), '');
  assert.equal(npmAuditJson([], () => ({ status: 1 })), '');
});

/**
 * Comando EXACTO del workflow bajo `bash -eo pipefail` con un `npm` falso en
 * PATH que sale con exit 1 (como el real cuando hay advisories).
 */
function runWorkflowCommand(args, fakeStdout) {
  const dir = mkdtempSync(path.join(tmpdir(), 'fake-npm-'));
  const bin = path.join(dir, 'npm');
  writeFileSync(bin, `#!/bin/sh\necho "$@" > "$(dirname "$0")/args.txt"\ncat <<'JSON'\n${fakeStdout}\nJSON\nexit 1\n`);
  chmodSync(bin, 0o755);
  const node = path.dirname(process.execPath);
  const res = spawnSync('bash', ['-eo', 'pipefail', '-c', `node scripts/npm-audit-gate.mjs ${args}`], {
    encoding: 'utf8',
    env: { ...process.env, PATH: `${dir}:${node}:/usr/bin:/bin` },
  });
  res.npmArgs = readFileSync(path.join(dir, 'args.txt'), 'utf8').trim();
  return res;
}

test('workflow bajo bash -eo pipefail: npm sale 1 con solo picomatch -> rc 0', () => {
  const res = runWorkflowCommand('--omit=dev', JSON.stringify(report(PICOMATCH)));
  assert.equal(res.status, 0, res.stderr);
  assert.match(res.stdout, /ghsa-fc5q-39xc-vjpf ignorada/);
  assert.equal(res.npmArgs, 'audit --json --omit=dev');
});

test('workflow bajo bash -eo pipefail: advisory ajena inyectada -> rc 1 y se nombra', () => {
  const res = runWorkflowCommand('', JSON.stringify(report(PICOMATCH, OTHER)));
  assert.equal(res.status, 1);
  assert.match(res.stderr, /left-pad/);
  assert.equal(res.npmArgs, 'audit --json');
});

test('workflow bajo bash -eo pipefail: salida no JSON o vacia de npm -> rc 1', () => {
  assert.equal(runWorkflowCommand('', '<html>502</html>').status, 1);
  assert.equal(runWorkflowCommand('', '').status, 1);
});

test('--stdin: lee el JSON de stdin', () => {
  const ok = spawnSync(process.execPath, ['scripts/npm-audit-gate.mjs', '--stdin'], { input: JSON.stringify(report(PICOMATCH)), encoding: 'utf8' });
  assert.equal(ok.status, 0);
  const bad = spawnSync(process.execPath, ['scripts/npm-audit-gate.mjs', '--stdin'], { input: '', encoding: 'utf8' });
  assert.equal(bad.status, 1);
});


test('falla cerrado ante un mapa o nodo de vulnerabilidades incompleto', () => {
  for (const vulnerabilities of [[], "bad", { pkg: null }, { pkg: [] },
    { pkg: { via: [] } }, { pkg: { severity: "HIGH", via: [] } },
    { pkg: { severity: "high" } }]) {
    const result = evaluateAudit({ vulnerabilities });
    assert.equal(result.ok, false);
    assert.equal(typeof result.error, 'string');
  }
});

test('una advisory raiz malformada no se omite ni hace caer el parser', () => {
  for (const via of [null, [], 42, "", { ...OTHER, severity: undefined },
    { ...OTHER, severity: "unknown" }, { ...OTHER, name: null },
    { ...OTHER, title: null }, { ...OTHER, url: null }]) {
    const result = evaluateAudit({ vulnerabilities: { pkg: { severity: 'high', via: [via] } } });
    assert.equal(result.ok, false);
    assert.equal(typeof result.error, 'string');
  }
});

test('valida tambien nodos no bloqueantes antes de declarar un informe limpio', () => {
  const result = evaluateAudit({ vulnerabilities: { pkg: { severity: 'low', via: [null] } } });
  assert.equal(result.ok, false);
  assert.equal(evaluateAudit(report({ ...OTHER, severity: 'info' })).ok, true);
  assert.equal(evaluateAudit(report({ ...OTHER, severity: 'low' })).ok, true);
});
