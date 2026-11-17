/**
 * Puerta de `npm audit` del job "Dependency audits".
 *
 * Uso (CI):  node scripts/npm-audit-gate.mjs [--omit=dev]
 * El script ejecuta `npm audit --json`, captura su salida y IGNORA el
 * exit code de npm (sale 1 cuando hay advisories, que es justo lo que se
 * evalua aqui); decide por su cuenta. Un `npm audit | gate` falla bajo
 * `bash -eo pipefail` de GitHub aunque el gate diga que esta permitido.
 * `--stdin` lee el JSON de stdin en vez de ejecutar npm (tests).
 *
 * Equivale a `npm audit --audit-level=high` con UNA excepcion explicita y
 * caducable (IGNORED_ADVISORIES). Cualquier otra advisory high/critical sigue
 * tumbando el job. Falla cerrado: entrada vacia, JSON ilegible o respuesta de
 * error de npm (registro caido) son rojo, nunca verde.
 */
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

/**
 * EXCEPCION TEMPORAL (alta 17-nov-2026).
 * GHSA-fc5q-39xc-vjpf (CVE-2026-112366): ReDoS en picomatch <= 4.0.7. GitHub
 * publica first_patched_version = null y npm `latest` es 4.0.7: no hay version
 * a la que subir. Llega por vitest/vite/tinyglobby/fdir (devDependencies;
 * better-auth declara vitest como peer opcional y por eso npm lo cuenta en
 * --omit=dev). La imagen final solo copia .next/standalone: no se envia.
 *
 * RETIRAR cuando exista picomatch > 4.0.7: subir picomatch (override o
 * lockfile), borrar esta entrada y comprobar que `npm audit` da 0.
 * Revision diaria: `npm view picomatch dist-tags.latest` y
 * https://github.com/advisories/GHSA-fc5q-39xc-vjpf (first_patched_version).
 */
export const IGNORED_ADVISORIES = new Set(['GHSA-fc5q-39xc-vjpf']);

const BLOCKING = new Set(['high', 'critical']);

const GHSA_RE = /GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}/i;

/**
 * Advisories raiz alcanzables desde un paquete siguiendo sus cadenas `via`.
 * `unresolved` = alguna cadena apunta a un paquete que no esta en el informe
 * (grafo incompleto). Los ciclos se cortan con `visited`.
 */
function rootAdvisories(vulnerabilities, start) {
  const advisories = [];
  let unresolved = false;
  const visited = new Set();
  const stack = [start];
  while (stack.length > 0) {
    const name = stack.pop();
    if (visited.has(name)) continue;
    visited.add(name);
    const node = vulnerabilities[name];
    if (!node || !Array.isArray(node.via)) {
      unresolved = true;
      continue;
    }
    for (const via of node.via) {
      if (typeof via === 'string') stack.push(via);
      else advisories.push(via);
    }
  }
  return { advisories, unresolved };
}

/**
 * @param {unknown} report salida de `npm audit --json`
 * @returns {{ ok: boolean, blocking: {name:string,severity:string,title:string,url:string}[], ignored: string[], error?: string }}
 */
export function evaluateAudit(report, ignored = IGNORED_ADVISORIES) {
  const fail = (error) => ({ ok: false, blocking: [], ignored: [], error });
  if (!report || typeof report !== 'object') return fail('respuesta de npm audit vacia o no es un objeto');
  if (report.error) return fail(`npm audit devolvio un error: ${report.error.summary}`);
  const vulns = report.vulnerabilities;
  if (!vulns || typeof vulns !== 'object') return fail('sin campo vulnerabilities en la salida de npm audit');

  const ignoredLower = new Set([...ignored].map((id) => id.toLowerCase()));
  const blocking = [];
  const seenIgnored = new Set();
  const seen = new Set();
  const block = (name, severity, title, url) => {
    const key = `${name}|${url}|${title}`;
    if (seen.has(key)) return;
    seen.add(key);
    blocking.push({ name, severity, title, url });
  };
  for (const [name, vuln] of Object.entries(vulns)) {
    if (!BLOCKING.has(vuln.severity)) continue;
    const { advisories, unresolved } = rootAdvisories(vulns, name);
    const serious = advisories.filter((via) => BLOCKING.has(via.severity));
    // Cadena rota o paquete high sin advisory raiz atribuible: no puede
    // acogerse a la excepcion (falla cerrado).
    if (unresolved || serious.length === 0) block(name, vuln.severity, 'severidad alta sin cadena atribuible hasta una advisory raiz', '');
    for (const via of serious) {
      const ghsa = GHSA_RE.exec(via.url)?.[0].toLowerCase();
      if (ignoredLower.has(ghsa)) seenIgnored.add(ghsa);
      else block(via.name, via.severity, via.title, via.url);
    }
  }
  return { ok: blocking.length === 0, blocking, ignored: [...seenIgnored].sort() };
}

/** Decide codigo de salida y mensajes a partir del texto crudo del JSON de npm. */
export function runGate(raw) {
  let report;
  try {
    report = JSON.parse(raw);
  } catch {
    return { code: 1, out: [], err: ['npm-audit-gate: la salida de `npm audit --json` no es JSON.'] };
  }
  const result = evaluateAudit(report);
  if (result.error) return { code: 1, out: [], err: [`npm-audit-gate: ${result.error}`] };
  const out = result.ignored.map(
    (id) => `npm-audit-gate: ${id} ignorada (excepcion temporal, ver IGNORED_ADVISORIES en scripts/npm-audit-gate.mjs; retirar cuando haya picomatch > 4.0.7).`,
  );
  if (!result.ok) {
    const err = ['npm-audit-gate: advisories high/critical sin excepcion:', ...result.blocking.map((b) => `  - ${b.name} [${b.severity}] ${b.title} ${b.url}`)];
    return { code: 1, out, err };
  }
  return { code: 0, out: [...out, 'npm-audit-gate: sin advisories high/critical fuera de la excepcion.'], err: [] };
}

/**
 * Ejecuta `npm audit --json` y devuelve su stdout. El exit code de npm no
 * cuenta (1 = hay advisories); si npm no arranca (error de spawn) o no
 * imprime nada, runGate recibe texto vacio y falla cerrado.
 */
export function npmAuditJson(args, spawn = spawnSync) {
  const res = spawn('npm', ['audit', '--json', ...args], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, shell: process.platform === 'win32' });
  return res.error ? '' : String(res.stdout ?? '');
}

/* node:coverage ignore next 14 */
async function main() {
  const argv = process.argv.slice(2);
  let raw;
  if (argv.includes('--stdin')) {
    const chunks = [];
    for await (const chunk of process.stdin) chunks.push(chunk);
    raw = Buffer.concat(chunks).toString('utf8');
  } else {
    raw = npmAuditJson(argv.filter((a) => a === '--omit=dev'));
  }
  const { code, out, err } = runGate(raw);
  for (const line of out) console.log(line);
  for (const line of err) console.error(line);
  process.exit(code);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) await main();
