import { spawnSync } from 'node:child_process';
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { hasSharedScope, partitionRoots, runTypecheck } from './typecheck.mjs';

describe('typecheck partition preserves the gate', () => {
  it('covers all roots, includes new directories by default and shares declarations', () => {
    const root = '/repo';
    const files = ['app/page.tsx', 'tests/a.ts', 'scripts/a.ts', 'e2e/a.ts', 'future/x.ts', 'types/global.d.ts'].map(f => path.join(root, f));
    const groups = partitionRoots(files, root, file => file.endsWith('.d.ts'));
    assert.deepEqual(new Set(Object.values(groups).flat()), new Set(files));
    assert.ok(groups.app.includes('/repo/future/x.ts'));
    for (const group of Object.values(groups)) assert.ok(group.includes('/repo/types/global.d.ts'));
  });
  for (const failing of ['app', 'tests', 'scripts', 'e2e']) {
    it(`propagates a compiler failure in ${failing} and cleans generated configs`, () => {
      const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-gate-'));
      try {
        fs.writeFileSync(path.join(root, 'tsconfig.json'), JSON.stringify({ compilerOptions: { strict: true, types: [], skipLibCheck: true }, include: ['**/*.ts'] }));
        for (const group of ['app', 'tests', 'scripts', 'e2e']) {
          fs.mkdirSync(path.join(root, group));
          fs.writeFileSync(path.join(root, group, 'sample.ts'), 'export const value: number = 1;');
        }
        const visited = [];
        const status = runTypecheck(root, (binary, args) => {
          assert.ok(args.includes('--max-old-space-size=1408'));
          const config = JSON.parse(fs.readFileSync(args.at(-1), 'utf8'));
          assert.equal(config.extends, path.join(root, 'tsconfig.json'));
          const name = path.basename(args.at(-1), '.json');
          visited.push(name);
          return { status: name === failing ? 2 : 0 };
        });
        assert.equal(status, 2);
        assert.equal(visited.at(-1), failing);
        assert.ok(!fs.readdirSync(root).some(name => name.startsWith('.typecheck-')));
      } finally { fs.rmSync(root, { recursive: true, force: true }); }
    });
  }
});

it('real compiler rejects an intentional type error in each family', () => {
  for (const group of ['app', 'tests', 'scripts', 'e2e']) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-negative-'));
    try {
      fs.symlinkSync(path.resolve('node_modules'), path.join(root, 'node_modules'), 'dir');
      fs.writeFileSync(path.join(root, 'tsconfig.json'), JSON.stringify({
        compilerOptions: { strict: true, skipLibCheck: true, noEmit: true, types: [] }, include: ['**/*.ts'],
      }));
      for (const directory of ['app', 'tests', 'scripts', 'e2e']) {
        fs.mkdirSync(path.join(root, directory));
        fs.writeFileSync(path.join(root, directory, 'sample.ts'), directory === group
          ? 'export const value: number = "intentional type error";'
          : 'export const value: number = 1;');
      }
      assert.equal(runTypecheck(root), 2);
    } finally { fs.rmSync(root, { recursive: true, force: true }); }
  }
});

for (const outcome of [{ status: 0 }, { status: null }, { error: new Error('spawn failed') }]) {
  it(`handles compiler outcome ${outcome.error?.message ?? outcome.status} and removes temporary configs`, () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-outcome-'));
    try {
      fs.writeFileSync(path.join(root, 'tsconfig.json'), JSON.stringify({ compilerOptions: { types: [], skipLibCheck: true }, files: ['sample.ts'] }));
      fs.writeFileSync(path.join(root, 'sample.ts'), 'export {};');
      let spawns = 0;
      assert.equal(runTypecheck(root, (_binary, args) => {
        assert.ok(args.includes('--max-old-space-size=1408'));
        spawns++;
        return outcome;
      }), outcome.status === 0 ? 0 : 1);
      assert.equal(spawns, outcome.status === 0 ? 4 : 1);
      assert.ok(!fs.readdirSync(root).some(name => name.startsWith('.typecheck-')));
    } finally { fs.rmSync(root, { recursive: true, force: true }); }
  });
}

for (const config of [null, '{broken json', JSON.stringify({ compilerOptions: { target: 'not-a-target' } })]) {
  it(`blocks invalid configuration ${config ?? 'missing file'} before any compiler spawn`, () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-config-'));
    try {
      if (config !== null) fs.writeFileSync(path.join(root, 'tsconfig.json'), config);
      let spawns = 0;
      assert.equal(runTypecheck(root, () => { spawns++; return { status: 0 }; }), 1);
      assert.equal(spawns, 0);
      assert.ok(!fs.readdirSync(root).some(name => name.startsWith('.typecheck-')));
    } finally { fs.rmSync(root, { recursive: true, force: true }); }
  });
}

for (const [name, first, second, diagnostic] of [
  ['global scripts', 'const sharedGlobal: number = 1;', 'const sharedGlobal: number = 1;', 'TS2451'],
  ['global augmentations', 'export {}; declare global { interface Shared { value: number } }', 'export {}; declare global { interface Shared { value: string } }', 'TS2717'],
]) {
  it(`preserves cross-family errors from ${name}`, () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-global-'));
    try {
      fs.symlinkSync(path.resolve('node_modules'), path.join(root, 'node_modules'), 'dir');
      fs.writeFileSync(path.join(root, 'tsconfig.json'), JSON.stringify({ compilerOptions: { strict: true, skipLibCheck: true, noEmit: true, types: [] }, include: ['**/*.ts'] }));
      for (const [group, text] of [['app', first], ['tests', second], ['scripts', 'export {};'], ['e2e', 'export {};']]) {
        fs.mkdirSync(path.join(root, group));
        fs.writeFileSync(path.join(root, group, 'sample.ts'), text);
      }
      const monolith = spawnSync(process.execPath, ['--max-old-space-size=1408', path.resolve('node_modules/typescript/bin/tsc'), '--noEmit', '-p', path.join(root, 'tsconfig.json')], { encoding: 'utf8' });
      assert.equal(monolith.status, 2);
      assert.ok(monolith.stdout.includes(diagnostic));
      assert.equal(runTypecheck(root), 2);
    } finally { fs.rmSync(root, { recursive: true, force: true }); }
  });
}

it('classifies shared declarations conservatively and fails closed on unreadable roots', () => {
  assert.equal(hasSharedScope('global.d.ts', () => { throw new Error('must not read declarations'); }), true);
  assert.equal(hasSharedScope('script.ts', () => 'const globalValue = 1;'), true);
  assert.equal(hasSharedScope('module.ts', () => 'export const local = 1;'), false);
  assert.equal(hasSharedScope('augment.ts', () => 'export {}; declare module "package" { interface Value {} }'), true);
  assert.throws(() => hasSharedScope('missing.ts', () => undefined), /Cannot read/);
});

it('preserves conflicting globals contributed only by transitive module dependencies', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-transitive-'));
  try {
    fs.symlinkSync(path.resolve('node_modules'), path.join(root, 'node_modules'), 'dir');
    fs.writeFileSync(path.join(root, 'tsconfig.json'), JSON.stringify({ compilerOptions: { strict: true, noEmit: true, skipLibCheck: true, types: [] }, include: ['app/*.ts', 'tests/*.ts'] }));
    for (const dir of ['app', 'tests', 'dependencies']) fs.mkdirSync(path.join(root, dir));
    fs.writeFileSync(path.join(root, 'app/root.ts'), 'import "../dependencies/first"; export {};');
    fs.writeFileSync(path.join(root, 'tests/root.ts'), 'import "../dependencies/second"; export {};');
    fs.writeFileSync(path.join(root, 'dependencies/first.ts'), 'export {}; declare global { interface TransitiveShared { value: number } }');
    fs.writeFileSync(path.join(root, 'dependencies/second.ts'), 'export {}; declare global { interface TransitiveShared { value: string } }');
    const monolith = spawnSync(process.execPath, ['--max-old-space-size=1408', path.resolve('node_modules/typescript/bin/tsc'), '--noEmit', '-p', path.join(root, 'tsconfig.json')], { encoding: 'utf8' });
    assert.equal(monolith.status, 2);
    assert.ok(monolith.stdout.includes('TS2717'));
    assert.equal(runTypecheck(root), 2);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
