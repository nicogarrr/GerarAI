/**
 * Ignored Build Step de Vercel: un merge que solo toca backend/docs/tests no
 * gasta un despliegue del cupo diario.
 *
 * Incidente 2026-10-27: ~140 merges en main, cada uno un despliegue de
 * produccion; desde #2381 todos en "Deployment rate limited — retry in 24
 * hours" y produccion congelada. Este guard ejecuta el script de verdad sobre
 * un repo git temporal y comprueba el contrato de Vercel (exit 0 = no
 * construir, exit 1 = construir), incluido el fallo abierto.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

const SCRIPT = path.resolve('scripts/vercel-ignore-build.sh');

function repo() {
  const dir = mkdtempSync(path.join(tmpdir(), 'vercel-ignore-'));
  const git = (...args: string[]) =>
    execFileSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@t', ...args], { cwd: dir }).toString().trim();
  git('init', '-q');
  const write = (file: string, body: string) => {
    mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
    writeFileSync(path.join(dir, file), body);
  };
  const commit = (msg: string) => {
    git('add', '-A');
    git('commit', '-q', '-m', msg);
    return git('rev-parse', 'HEAD');
  };
  const run = (prev: string | undefined) =>
    spawnSync('bash', [SCRIPT], {
      cwd: dir,
      env: { ...process.env, VERCEL_GIT_PREVIOUS_SHA: prev ?? '', VERCEL_GIT_COMMIT_SHA: 'HEAD' },
    }).status;
  write('app/page.tsx', 'a');
  write('data-engine/app/main.py', 'a');
  return { write, commit, run, base: commit('base') };
}

test('vercel.json desactiva TODOS los auto-deploys Git; manual solo por orden expresa', () => {
  const cfg = JSON.parse(readFileSync('vercel.json', 'utf8'));
  assert.equal(cfg.ignoreCommand, 'bash scripts/vercel-ignore-build.sh');
  assert.equal(cfg.git.deploymentEnabled, false);
});

test('solo backend, docs o tests desde el ultimo despliegue: no se construye (exit 0)', () => {
  const r = repo();
  r.write('data-engine/app/main.py', 'b');
  r.write('docs/x.md', 'b');
  r.write('README.md', 'b');
  r.write('scripts/algo-guard.test.ts', 'b');
  r.write('.github/workflows/ci.yml', 'b');
  r.commit('solo backend');
  assert.equal(r.run(r.base), 0);
});

test('cualquier cambio de frontend: se construye (exit 1)', () => {
  const r = repo();
  r.write('app/page.tsx', 'b');
  r.commit('frontend');
  assert.equal(r.run(r.base), 1);
});

test('un merge solo-backend no se salta un frontend cuyo despliegue fallo', () => {
  const r = repo();
  r.write('components/x.tsx', 'b');
  r.commit('frontend sin desplegar (rate limited)');
  r.write('data-engine/app/main.py', 'c');
  r.commit('backend');
  // El diff es contra el ultimo despliegue CORRECTO (base), no contra HEAD^.
  assert.equal(r.run(r.base), 1);
});

test('fallo abierto: sin SHA previo o SHA desconocido se construye', () => {
  const r = repo();
  assert.equal(r.run(undefined), 1);
  assert.equal(r.run('0123456789abcdef0123456789abcdef01234567'), 1);
});

test('package.json y dependencias cuentan como frontend', () => {
  const r = repo();
  r.write('package.json', '{}');
  r.commit('deps');
  assert.equal(r.run(r.base), 1);
});
