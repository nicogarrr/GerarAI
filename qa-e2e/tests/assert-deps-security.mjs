// Vigia de dependencias con advisory conocida (sin red, solo lee el lockfile).
// Rojo si alguna copia instalada de un paquete listado cae en rango vulnerable.
// Anadir entradas nuevas con el advisory + rango fijado.
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const lockPath = process.argv[2] ?? resolve(HERE, '..', 'package-lock.json');

// [paquete, version minima con parche, advisory]
const REGLAS = [
  // GHSA-mrhx-c7xc-m3w5: zod <4.6.6 agota memoria validando colecciones
  // grandes con restricciones (CWE-770, CVSS 7.5). Parche: 4.6.6.
  ['zod', [4, 6, 6], 'GHSA-mrhx-c7xc-m3w5'],
];

const cmp = (a, b) => a.reduce((acc, v, i) => acc || Math.sign(v - (b[i] ?? 0)), 0);
const parse = (v) => v.split('.').slice(0, 3).map((n) => parseInt(n, 10) || 0);

const lock = JSON.parse(readFileSync(lockPath, 'utf8'));
const fallos = [];
for (const [ruta, meta] of Object.entries(lock.packages ?? {})) {
  const nombre = ruta.split('node_modules/').pop();
  for (const [pkg, min, advisory] of REGLAS) {
    if (nombre !== pkg || !meta?.version) continue;
    if (cmp(parse(meta.version), min) < 0) {
      fallos.push(`${pkg}@${meta.version} (${ruta}) vulnerable a ${advisory}; minimo ${min.join('.')}`);
    }
  }
}
if (fallos.length) {
  console.error('DEPENDENCIAS VULNERABLES:\n - ' + fallos.join('\n - '));
  process.exit(1);
}
console.log(`OK: ${lockPath} sin versiones vulnerables conocidas (${REGLAS.length} reglas)`);
