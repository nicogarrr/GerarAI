import type { Metadata } from 'next';
import { Receipt } from 'lucide-react';
import TaxesView from '@/components/taxes/TaxesView';
import BackendOffline from '@/components/system/BackendOffline';
import { getModelo720File, getModelo720Thresholds, getTaxHoldings, getTaxReport, type TaxRecord } from '@/lib/actions/taxes.actions';
import { USER_TZ } from '@/lib/format';
import { getT } from '@/lib/i18n/server';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { isAppError, isAuthError } from '@/lib/types/errors';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
    const t = await getT();
    return {
        title: t('taxes.meta.title'),
        description: t('taxes.meta.description'),
    };
}

type PageProps = {
    searchParams: Promise<{ year?: string }>;
};

const MIN_YEAR = 2000;
const MAX_YEAR = 2200;

/** Una lectura que aísla su fallo: null es "no hay dato", no "backend caído". */
type Read<T> = { value: T; error: unknown };

function read<T>(promise: Promise<T>, fallback: T): Promise<Read<T>> {
    return promise
        .then((value) => ({ value, error: null }))
        .catch((error: unknown) => ({ value: fallback, error }));
}

/**
 * Un 4xx NO es el motor caído: es "este recurso no existe todavía" (por
 * ejemplo, no hay reporte fiscal para el ejercicio pedido). Se traduce al
 * estado vacío de la vista; el 5xx y el fetch fallido sí son BackendOffline.
 * Excepción: 401/403 no es "sin datos", es sesión caducada o acceso
 * denegado - se propaga (isAuthError), nunca se pinta como vacío.
 */
function isNotGeneratedYet(error: unknown): boolean {
    return isAppError(error) && error.statusCode >= 400 && error.statusCode < 500 && !isAuthError(error);
}

function asFiscalYear(raw: string | undefined): number {
    // El año fiscal del USUARIO, no el del runner: a las 00:30 del 1 de enero
    // en Madrid (23:30 del 31 de diciembre en UTC) `new Date().getFullYear()`
    // del servidor devolvía el ejercicio anterior. `en-CA` rinde "2026" con
    // year: 'numeric' y el instante se mide en USER_TZ (Europe/Madrid).
    const current = Number(new Intl.DateTimeFormat('en-CA', { timeZone: USER_TZ, year: 'numeric' }).format(new Date()));
    const parsed = raw ? Number.parseInt(raw, 10) : current;
    if (!Number.isInteger(parsed) || parsed < MIN_YEAR || parsed > MAX_YEAR) return current;
    return parsed;
}

export default async function TaxesPage({ searchParams }: PageProps) {
    const t = await getT();
    const fiscalYear = asFiscalYear((await searchParams)?.year);
    const [holdingsRead, reportRead, thresholdsRead, fileRead] = await Promise.all([
        read(getTaxHoldings(), [] as TaxRecord[]),
        read(getTaxReport(fiscalYear), null as TaxRecord | null),
        read(getModelo720Thresholds(fiscalYear), null as TaxRecord | null),
        read(getModelo720File(fiscalYear), null as TaxRecord | null),
    ]);
    const { error: holdingsError } = holdingsRead;
    const { error: reportError } = reportRead;
    // Un 401/403 no es "sin datos para este ejercicio": la sesión caducó o
    // el acceso cambió. Se propaga en vez de pintar el estado vacío de la
    // vista (holdings = [] / report = null) como si no hubiera nada.
    const authError = [holdingsRead, reportRead, thresholdsRead, fileRead].find(
        (r) => r.error && isAuthError(r.error),
    )?.error;
    if (authError) throw authError;
    // Los bloques del 720 son accesorios y no tumban la página, pero un
    // 4xx ("sin datos para este ejercicio") no es lo mismo que un 5xx o un
    // fallo de red ("indisponible"): el segundo se muestra como tal para no
    // aparentar que el 720 no aplica.
    const thresholds720 = thresholdsRead.error ? null : thresholdsRead.value;
    const file720 = fileRead.error ? null : fileRead.value;
    const thresholds720Unavailable = Boolean(
        thresholdsRead.error &&
        !isNotGeneratedYet(thresholdsRead.error) &&
        isBackendUnavailableError(thresholdsRead.error)
    ) || Boolean(
        thresholdsRead.error && !isNotGeneratedYet(thresholdsRead.error)
    );

    if (
        (holdingsError && isBackendUnavailableError(holdingsError)) ||
        (reportError && isBackendUnavailableError(reportError))
    ) {
        return <BackendOffline feature={t('taxes.meta.backendFeature')} retryHref={`/taxes?year=${fiscalYear}`} />;
    }
    if (holdingsError && !isNotGeneratedYet(holdingsError)) throw holdingsError;
    if (reportError && !isNotGeneratedYet(reportError)) throw reportError;

    // Cualquier otro fallo es un 4xx: el ejercicio no está generado todavía y
    // la vista ofrece su propio estado vacío con «Regenerar».
    const holdings = holdingsError ? [] : holdingsRead.value;
    const report = reportError ? null : reportRead.value;

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex max-w-6xl flex-col gap-6">
            <header className="flex flex-col gap-3 border-b border-gray-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
                <div>
                    <p className="text-sm font-semibold uppercase text-teal-300">{t('taxes.header.eyebrow')}</p>
                    <h1 className="mt-1 text-3xl font-bold text-gray-100">{t('taxes.header.title')}</h1>
                </div>
                <div className="flex items-center gap-2 rounded-lg border border-gray-800 bg-surface-1 px-3 py-2 text-sm text-gray-300">
                    <Receipt className="h-4 w-4 text-teal-300" />
                    {t('taxes.header.yearBadge', { year: fiscalYear })}
                </div>
            </header>

            <TaxesView initialHoldings={holdings} initialReport={report} initialThresholds720={thresholds720} initialFile720={file720} initialThresholds720Unavailable={thresholds720Unavailable} year={fiscalYear} />
        </main>
    );
}
