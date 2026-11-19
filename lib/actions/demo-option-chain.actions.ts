'use server';

/**
 * Cadena de opciones REAL diferida para el selector guiado del ticket demo
 * (tipo IBKR): dado un subyacente, devuelve vencimientos y strikes con la
 * última operación de cada contrato tal como la publica la delayed quotes
 * API de CBOE (retraso >= 15 min, hora de Nueva York).
 *
 * Reglas de ESTE fichero:
 * - Auth primero: requireAuthenticatedUser antes de tocar la fuente; el
 *   símbolo es el único dato del cliente y se valida aquí.
 * - Solo identidad + última operación: la respuesta NUNCA lleva bid/ask ni
 *   marca ninguna prima como actual; la prima diferida es referencia, no
 *   precio ejecutable (el ticket la muestra etiquetada y el precio de la
 *   orden lo escribe el usuario).
 * - Fracaso honesto: si la fuente no responde, está saturada o el subyacente
 *   no tiene opciones listadas, se devuelve el motivo y la UI ofrece la vía
 *   manual; nunca se inventan strikes ni vencimientos.
 * - Misma caché compartida que la valoración (lib/market/cboe-chain-cache.ts):
 *   consultar la cadena desde el ticket no duplica fetches de la fuente.
 */

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { sharedCboeChainCache } from '@/lib/market/cboe-chain-cache';

/** Vencimientos más próximos que se ofrecen en el selector (acotado para móvil). */
const MAX_CHAIN_EXPIRIES = 8;

import type {
    DemoOptionChainExpiry,
    DemoOptionChainResult,
    DemoOptionChainStrike,
} from '@/lib/paper-trading/option-chain-view';

export type { DemoOptionChainResult } from '@/lib/paper-trading/option-chain-view';

/** Raíz OCC razonable: 1-10 caracteres alfabéticos/punto/guión (BRK.B, SPXW). */
const SYMBOL_RE = /^[A-Za-z][A-Za-z.-]{0,9}$/;

export async function getDemoOptionChain(rawSymbol: unknown): Promise<DemoOptionChainResult> {
    try {
        await requireAuthenticatedUser();
    } catch {
        return { ok: false, reason: 'noAuth' };
    }
    if (typeof rawSymbol !== 'string') return { ok: false, reason: 'invalidSymbol' };
    const underlying = rawSymbol.trim().toUpperCase();
    if (!SYMBOL_RE.test(underlying)) return { ok: false, reason: 'invalidSymbol' };

    const attempt = await sharedCboeChainCache.getChain(underlying);
    if (attempt.saturated) return { ok: false, reason: 'saturated' };
    if (attempt.fetchFailed || attempt.chain === null || attempt.fetchedAt === null) {
        return { ok: false, reason: 'sourceUnavailable' };
    }

    // Clave canónica "SUBYACENTE|aaaa-mm-dd|call|put|strike*1000" (cboeContractKey).
    const byExpiry = new Map<string, Map<number, DemoOptionChainStrike>>();
    for (const [key, premium] of attempt.chain) {
        const parts = key.split('|');
        if (parts.length !== 4) continue;
        const expiry = parts[1];
        const callPut = parts[2];
        const strike = Number(parts[3]) / 1000;
        if (callPut !== 'call' && callPut !== 'put') continue;
        if (!Number.isFinite(strike)) continue;
        let strikes = byExpiry.get(expiry);
        if (!strikes) {
            strikes = new Map();
            byExpiry.set(expiry, strikes);
        }
        let row = strikes.get(strike);
        if (!row) {
            row = { strike, call: null, put: null };
            strikes.set(strike, row);
        }
        const trade =
            premium.lastTradePrice !== null && premium.lastTradeTime !== null
                ? { price: premium.lastTradePrice, time: premium.lastTradeTime }
                : null;
        if (callPut === 'call') row.call = trade;
        else row.put = trade;
    }

    const expiries = [...byExpiry.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .slice(0, MAX_CHAIN_EXPIRIES)
        .map(([expiry, strikes]) => ({
            expiry,
            strikes: [...strikes.values()].sort((x, y) => x.strike - y.strike),
        }));

    if (expiries.length === 0) return { ok: false, reason: 'notCovered' };
    return { ok: true, underlying, fetchedAt: attempt.fetchedAt, expiries };
}
