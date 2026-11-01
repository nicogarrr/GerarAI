import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const HOOK = readFileSync('.githooks/pre-push', 'utf8');

// Feedback del piloto sobre el hook pre-push: borrados a lint (falso rojo),
// rutas con espacios partidas, ref remoto ausente = pasa sin chequear.
test('el hook es NUL-delimitado, excluye borrados y es fail-closed', () => {
    assert.match(HOOK, /--diff-filter=ACMR/, 'sin filtro de borrados');
    assert.match(HOOK, /git diff --name-only --diff-filter=ACMR -z/, 'diff no NUL');
    assert.match(HOOK, /xargs -0/, 'xargs sin -0 parte los espacios');
    assert.doesNotMatch(HOOK, /tr ' '/, 'tr espacio->salto parte rutas con espacios');
    assert.match(HOOK, /fail-closed/, 'sin camino fail-closed');
    assert.match(HOOK, /git fetch -q origin main/, 'sin fetch de la base ausente');
});

// Banco de pruebas real: repo temporal + shims de npx/uv que registran args.
function makeRepo() {
    const dir = mkdtempSync(join(tmpdir(), 'prepush-'));
    const git = (...args: string[]) => execFileSync('git', args, { cwd: dir, stdio: 'pipe' });
    git('init', '-q', '-b', 'main');
    git('config', 'user.email', 't@t.t');
    git('config', 'user.name', 't');
    mkdirSync(join(dir, 'src'), { recursive: true });
    mkdirSync(join(dir, 'data-engine'), { recursive: true });
    writeFileSync(join(dir, 'src', 'ok.ts'), 'export const a = 1;\n');
    writeFileSync(join(dir, 'src', 'con espacio.ts'), 'export const b = 2;\n');
    writeFileSync(join(dir, 'src', 'borrado.ts'), 'export const c = 3;\n');
    writeFileSync(join(dir, 'data-engine', 'mod.py'), 'X = 1\n');
    git('add', '-A');
    git('commit', '-qm', 'base');
    // Cambios: 2 ts modificados (uno con espacios), 1 ts BORRADO, 1 py.
    writeFileSync(join(dir, 'src', 'ok.ts'), 'export const a = 2;\n');
    writeFileSync(join(dir, 'src', 'con espacio.ts'), 'export const b = 3;\n');
    rmSync(join(dir, 'src', 'borrado.ts'));
    writeFileSync(join(dir, 'data-engine', 'mod.py'), 'X = 2\n');
    git('add', '-A');
    git('commit', '-qm', 'cambios');
    return { dir, git, head: git('rev-parse', 'HEAD').toString().trim() };
}

function makeShims(dir: string) {
    const bin = join(dir, 'bin');
    mkdirSync(bin);
    const log = join(dir, 'lint.log');
    for (const tool of ['npx', 'uv']) {
        writeFileSync(join(bin, tool), `#!/bin/sh\nprintf '%s\\n' "$@" >> "${log}"\nexit 0\n`, { mode: 0o755 });
    }
    return log;
}

function runHook(dir: string, { withOriginMain = true } = {}) {
    const { git } = { git: (...a: string[]) => execFileSync('git', a, { cwd: dir, stdio: 'pipe' }) };
    if (withOriginMain) {
        git('update-ref', 'refs/remotes/origin/main', 'HEAD~1');
    }
    const log = makeShims(dir);
    const head = git('rev-parse', 'HEAD').toString().trim();
    const zero = '0'.repeat(40);
    const res = spawnSync('bash', ['.githooks/pre-push'], {
        cwd: dir,
        input: `refs/heads/feat ${head} refs/heads/feat ${zero}\n`,
        env: { ...process.env, PATH: `${join(dir, 'bin')}:${process.env.PATH}`, SKIP_TSC: '1' },
        encoding: 'utf8',
    });
    let args: string[] = [];
    try {
        args = readFileSync(log, 'utf8').split('\n').filter(Boolean);
    } catch { /* sin lint */ }
    return { res, args };
}

test('borrados no van a lint y las rutas con espacios llegan como UN argumento', () => {
    const { dir } = makeRepo();
    writeFileSync(join(dir, '.githooks-placeholder'), '');
    mkdirSync(join(dir, '.githooks'));
    writeFileSync(join(dir, '.githooks', 'pre-push'), HOOK, { mode: 0o755 });
    const { res, args } = runHook(dir);
    assert.equal(res.status, 0, res.stderr);
    assert.ok(args.includes('src/con espacio.ts'), `ruta con espacios partida: ${JSON.stringify(args)}`);
    assert.ok(args.includes('src/ok.ts'), 'falta ok.ts');
    assert.ok(!args.some((a) => a.includes('borrado')), `borrado mandado a lint: ${JSON.stringify(args)}`);
    assert.ok(args.includes('mod.py'), 'falta el py (ruta relativa a data-engine)');
});

test('sin ref remoto ni fetch posible: sale 1 SIN chequear (fail-closed)', () => {
    const { dir } = makeRepo();
    mkdirSync(join(dir, '.githooks'));
    writeFileSync(join(dir, '.githooks', 'pre-push'), HOOK, { mode: 0o755 });
    const { res, args } = runHook(dir, { withOriginMain: false });
    assert.equal(res.status, 1, `debio fallar cerrado: ${res.stdout}${res.stderr}`);
    assert.equal(args.length, 0, `lint corrio sin base: ${JSON.stringify(args)}`);
    assert.match(res.stderr, /fail-closed/);
});
