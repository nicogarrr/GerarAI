import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { holdersLines, insiderLines, ownershipText } from '@/lib/research/ownership-signals';

// Frases reales del backend, leídas de los .py: si cambian, el test lo nota.
const PY = readFileSync('data-engine/app/services/ticker_ownership_signals.py', 'utf8');
const OVERLAP = readFileSync('data-engine/app/services/investor_overlap.py', 'utf8');
const CLUSTER = PY.match(/CLUSTER_MIN_INSIDERS = (\d+)/)![1];
const join = (block: string) => [...block.matchAll(/f?"([^"]*)"/g)].map((m) => m[1]).join('');
const fill = (text: string) => text.replace('{CLUSTER_MIN_INSIDERS}', CLUSTER).replace('{normalized}', 'ACME').replace('{window_days}', '180');

const READINGS = [...PY.matchAll(/reading = (f?"[^"]+")/g)].map((m) => fill(join(m[1])));
const DETAILS = [
    ...[...PY.matchAll(/"detail": \(\s*((?:f?"[^"]*"\s*)+)\)/g)].map((m) => fill(join(m[1]))),
    ...[...PY.matchAll(/"detail": (f?"[^"]+"),/g)].map((m) => fill(join(m[1]))),
    ...[...PY.matchAll(/or "([^"]+)",?\s*\n/g)].map((m) => m[1]),
];
const IDENTITY = [...OVERLAP.matchAll(/return None, "([^"]+)"/g)].map((m) => m[1]);
const SPANISH = /[áéíóúñ]|\b(Sin|sin|de|los|las|en|no hay|Compras|Ventas|Identidad|registrado|Referencia)\b/;

describe('Insiders y 13F: lectura y motivos del backend en inglés', () => {
    it('lee las 4 lecturas, los motivos y las identidades del backend', () => {
        expect(READINGS).toEqual([`Compras en grupo de insiders (${CLUSTER} o más)`, 'Compras netas de insiders', 'Ventas netas de insiders', 'Sin balance claro de insiders']);
        expect(DETAILS.length).toBeGreaterThanOrEqual(5);
        expect(IDENTITY.length).toBeGreaterThanOrEqual(7);
    });

    it.each([...READINGS, ...DETAILS, ...IDENTITY])('en inglés, sin castellano: %s', (text) => {
        expect(ownershipText(text, 'en')).not.toMatch(SPANISH);
    });

    it('en castellano, tal cual', () => {
        for (const text of [...READINGS, ...DETAILS, ...IDENTITY]) expect(ownershipText(text, 'es')).toBe(text);
    });

    it('un bloque sin datos enseña el motivo en inglés', () => {
        const noTrades = DETAILS.find((d) => d.startsWith('Sin compras ni ventas'))!;
        expect(insiderLines({ status: 'sin_datos', detail: noTrades }, 'en')).toEqual(['No open-market insider buys or sells (Form 4) stored for ACME in the last 180 days.']);
        const universe = DETAILS.find((d) => d.includes('universo'))!;
        expect(holdersLines({ status: 'sin_datos', detail: universe }, 'en')).toEqual(['ACME is not in the company universe: no 13F cross-check.']);
        expect(holdersLines({ status: 'sin_datos', detail: universe }, 'es')).toEqual([universe]);
    });

    it('un texto desconocido pasa tal cual', () => {
        expect(ownershipText('Otro motivo', 'en')).toBe('Otro motivo');
    });
});
