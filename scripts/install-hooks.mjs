// Engancha .githooks via core.hooksPath (npm lo ejecuta en `prepare`).
// Idempotente; no pisa un hooksPath distinto ya configurado.
import { execSync } from 'node:child_process';

let current = '';
try {
    current = execSync('git config core.hooksPath', { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
} catch {
    // Sin valor previo (git config devuelve 1): se fija abajo.
}
if (!current) {
    try {
        execSync('git config core.hooksPath .githooks');
        console.log('[install-hooks] core.hooksPath=.githooks activado (pre-push rapido).');
    } catch {
        // Sin repo git (tarball, CI parcial): nada que enganchar.
    }
} else if (current !== '.githooks') {
    console.log(`[install-hooks] core.hooksPath ya es '${current}': no se toca.`);
}
