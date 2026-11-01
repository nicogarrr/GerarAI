/**
 * Validación pura (sin alias ni React) de snapshots mensuales cargados desde
 * un archivo JSON (F384/F385).
 */
import type { MonthlySnapshot } from './monthlyRebalance';

/** Type guard para snapshots cargados desde un archivo JSON. */
export function isMonthlySnapshot(value: unknown): value is MonthlySnapshot {
    if (typeof value !== 'object' || value === null) return false;
    const v = value as Record<string, unknown>;
    return (
        v.kind === 'cavaai-propicks-monthly-snapshot' &&
        Array.isArray(v.picks) &&
        // F385: un pick null o sin símbolo rompía diffSnapshots (TypeError).
        v.picks.every(
            (pick) =>
                typeof pick === 'object' &&
                pick !== null &&
                typeof (pick as Record<string, unknown>).symbol === 'string' &&
                (pick as Record<string, unknown>).symbol !== '',
        ) &&
        typeof v.month === 'string' &&
        /^\d{4}-(0[1-9]|1[0-2])$/.test(v.month) &&
        typeof v.strategyId === 'string'
    );
}

/**
 * F384: el snapshot «anterior» debe ser de la misma estrategia y de un mes
 * estrictamente anterior al actual. Devuelve el motivo del rechazo o null.
 */
export function previousSnapshotRejection(
    snapshot: MonthlySnapshot,
    strategyId: string,
    currentMonth: string,
): 'otherStrategy' | 'notPrevious' | null {
    if (snapshot.strategyId !== strategyId) return 'otherStrategy';
    if (snapshot.month >= currentMonth) return 'notPrevious';
    return null;
}

export function previousSnapshotError(
    snapshot: MonthlySnapshot,
    strategyId: string,
    currentMonth: string,
): string | null {
    const rejection = previousSnapshotRejection(snapshot, strategyId, currentMonth);
    if (rejection === 'otherStrategy') {
        return 'Ese snapshot es de otra estrategia: no se puede comparar con la actual.';
    }
    if (rejection === 'notPrevious') {
        return 'Ese snapshot no es de un mes anterior al actual.';
    }
    return null;
}
