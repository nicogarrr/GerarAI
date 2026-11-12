import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { extname, join } from 'node:path';
import test from 'node:test';

/**
 * Guard: los porcentajes de los recorridos principales (ficha, Informe,
 * cartera, watchlist) salen del helper compartido `formatPercent` (lib/format.ts
 * o `useFormat()`/`getFormat()`), no de un número con «%» pegado a mano.
 *
 * Por qué: en es-ES el porcentaje lleva espacio duro antes del signo
 * («12,3 %», como hace formatPercent con Intl) y en inglés no («12.3%»). Con el
 * «%» pegado a mano, la misma pantalla mezclaba «12,3%» y «12,3 %» (cartera:
 * previsión y dividendos; ficha: capital social, cobertura del terminal; cortos
 * públicos) y en inglés salía «12.3 %» donde el texto sí venía del helper.
 * Origen: auditoría i18n de r5-a11y, 12-nov-2026.
 *
 * Ejecución: node --experimental-strip-types --test scripts/percent-format-guard.test.ts
 */

const ROOTS = [
    'components/research', 'components/watchlist', 'components/portfolio',
    'app/(root)/research', 'app/(root)/watchlist', 'app/(root)/portfolio', 'app/(root)/inicio',
];
/** Excepciones con motivo. */
const ALLOW: Record<string, string> = {
    // El aviso repite el número tal cual lo tecleó el usuario en el campo (sin redondear).
    'components/research/QuickAlertPopoverBody.tsx': 'eco literal de lo tecleado',
};

const walk = (dir: string, out: string[] = []): string[] => {
    for (const entry of readdirSync(dir)) {
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) walk(full, out);
        else if (extname(full) === '.tsx' && !/\.(test|spec)\.tsx$/.test(full)) out.push(full);
    }
    return out;
};

/** Trozos de JSX/plantilla donde un número interpolado lleva «%» pegado o con espacio normal. */
export function handGluedPercents(source: string): string[] {
    const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
    const hits: string[] = [];
    // `${n}%`  `${n} %`  {formatNumber(...)}%  {n} %  .toFixed(0)}%
    for (const m of code.matchAll(/\}[ ]?%(?=[`<\s·),"']|$)/gm)) {
        const before = code.slice(Math.max(0, m.index! - 80), m.index! + m[0].length);
        // CSS en línea (width: `${x}%`) no es texto visible.
        if (/(width|height|left|right|top|bottom|translate|inset|flexBasis|max-w|min-w|w-\[|h-\[)[^`]*$/.test(before.split('`').slice(-2, -1)[0] ?? '') || /(width|height|left|right|top|bottom|flexBasis)\s*:\s*`[^`]*$/.test(before)) continue;
        hits.push(before.replace(/\s+/g, ' ').trim().slice(-70));
    }
    return hits;
}

test('detector: marca «%» pegado a mano y deja pasar estilos y el helper', () => {
    assert.equal(handGluedPercents('const a = `${f.formatNumber(x * 100)}%`;').length, 1);
    assert.equal(handGluedPercents('<dd>{formatNumber(row.percent)}% · fuente</dd>').length, 1);
    assert.equal(handGluedPercents('const a = `${terminal.coverage.percent.toFixed(0)}%`;').length, 1);
    assert.equal(handGluedPercents('<div style={{ width: `${pct}%` }} />').length, 0);
    assert.equal(handGluedPercents('<dd>{f.formatPercent(x, { digits: 1 })}</dd>').length, 0);
});

test('los porcentajes de ficha, Informe, cartera y watchlist salen de formatPercent', () => {
    const offenders: string[] = [];
    for (const root of ROOTS) {
        for (const file of walk(root)) {
            const rel = file.split('\\').join('/');
            if (rel in ALLOW) continue;
            for (const hit of handGluedPercents(readFileSync(file, 'utf8'))) offenders.push(`${rel}: …${hit}`);
        }
    }
    assert.deepEqual(offenders, [], `porcentajes con «%» pegado a mano:\n${offenders.join('\n')}`);
});
