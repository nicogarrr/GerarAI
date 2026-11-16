/** Check the exact tsconfig root set in bounded sequential compiler processes. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import ts from 'typescript';

export function hasSharedScope(file, read = ts.sys.readFile) {
  if (file.endsWith('.d.ts')) return true;
  const text = read(file);
  if (text === undefined) throw new Error(`Cannot read TypeScript root: ${file}`);
  return sourceHasSharedScope(ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true));
}

function sourceHasSharedScope(source) {
  if (!ts.isExternalModule(source)) return true;
  // External modules may still contribute global or ambient module declarations.
  const augments = node => (ts.isModuleDeclaration(node) &&
    ((node.flags & ts.NodeFlags.GlobalAugmentation) !== 0 || ts.isStringLiteral(node.name))) ||
    ts.forEachChild(node, augments);
  return Boolean(augments(source));
}

export function partitionRoots(files, root, sharedScope = hasSharedScope) {
  const groups = { app: [], tests: [], scripts: [], e2e: [] };
  const shared = files.filter(file => sharedScope(file));
  for (const file of files) {
    const directory = path.relative(root, file).split(path.sep)[0];
    const group = Object.hasOwn(groups, directory) ? directory : 'app';
    groups[group].push(file);
  }
  for (const key of Object.keys(groups)) groups[key] = [...new Set([...shared, ...groups[key]])];
  const union = new Set(Object.values(groups).flat());
  if (union.size !== new Set(files).size || files.some(file => !union.has(file))) {
    throw new Error('Typecheck partition changed the configured root set');
  }
  return groups;
}

export function runTypecheck(root, run = spawnSync) {
  const configPath = path.join(root, 'tsconfig.json');
  const read = ts.readConfigFile(configPath, ts.sys.readFile);
  const parsed = ts.parseJsonConfigFileContent(read.config ?? {}, ts.sys, root);
  const errors = [read.error, ...parsed.errors].filter(Boolean);
  if (errors.length) {
    console.error(ts.formatDiagnosticsWithColorAndContext(errors, {
      getCanonicalFileName: f => f, getCurrentDirectory: () => root, getNewLine: () => os.EOL,
    }));
    return 1;
  }
  const groups = partitionRoots(parsed.fileNames, root);
  // Ambient effects can come from transitive dependencies, not just roots.
  // Use the original compiler graph so every partition sees the same globals.
  const planned = spawnSync(process.execPath, ['--max-old-space-size=1408', fileURLToPath(import.meta.url), '--plan', root], { encoding: 'utf8' });
  if (planned.status !== 0) { console.error(planned.stderr || planned.error?.message); return planned.status ?? 1; }
  const ambient = JSON.parse(planned.stdout);
  for (const name of Object.keys(groups)) groups[name] = [...new Set([...groups[name], ...ambient])];
  // The config lives under the repository, preserving automatic @types lookup.
  // It extends the original unchanged; aliases, strictness and Next types stay.
  const temporary = fs.mkdtempSync(path.join(root, '.typecheck-'));
  try {
    for (const [name, files] of Object.entries(groups)) {
      const config = path.join(temporary, `${name}.json`);
      fs.writeFileSync(config, JSON.stringify({
        extends: configPath,
        compilerOptions: { tsBuildInfoFile: path.join(temporary, `${name}.tsbuildinfo`) },
        files, include: [], exclude: [],
      }));
      console.log(`typecheck: ${name} (${files.length} roots, 1408 MB heap)`);
      const result = run(process.execPath, [
        '--max-old-space-size=1408', path.join(root, 'node_modules/typescript/bin/tsc'),
        '--noEmit', '--project', config,
      ], { cwd: root, stdio: 'inherit' });
      if (result.error) { console.error(result.error.message); return 1; }
      if (result.status !== 0) return result.status ?? 1;
    }
    return 0;
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv[2] === '--plan') {
    const root = process.argv[3];
    const read = ts.readConfigFile(path.join(root, 'tsconfig.json'), ts.sys.readFile);
    const parsed = ts.parseJsonConfigFileContent(read.config, ts.sys, root);
    const program = ts.createProgram({ rootNames: parsed.fileNames, options: parsed.options });
    const ambient = program.getSourceFiles().filter(source => source.isDeclarationFile || sourceHasSharedScope(source)).map(source => source.fileName);
    process.stdout.write(JSON.stringify(ambient));
  } else {
    process.exitCode = runTypecheck(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'));
  }
}
