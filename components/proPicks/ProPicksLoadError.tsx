import Link from 'next/link';
import { RefreshCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';

/** Un fallo de la consulta local no es una comprobación de salud del motor. */
export default function ProPicksLoadError({ statusCode, locale = DEFAULT_LOCALE }: { statusCode?: number; locale?: Locale }) {
    const t = createTranslator(locale);
    const message = statusCode === 401 || statusCode === 403
        ? t('propicks.loadError.session')
        : statusCode === 429
            ? t('propicks.loadError.rateLimited')
            : statusCode !== undefined && statusCode >= 400 && statusCode < 500
                ? t('propicks.loadError.request')
                : t('propicks.loadError.generic');

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-2xl flex-col items-center gap-5 px-4 py-24 text-center">
            <h1 className="text-2xl font-bold text-gray-100">{t('propicks.loadError.title')}</h1>
            <p role="alert" className="max-w-md text-sm leading-6 text-gray-400">{message}</p>
            <Button asChild className="min-h-11">
                <Link href="/propicks"><RefreshCcw aria-hidden="true" className="h-4 w-4" />{t('common.actions.retry')}</Link>
            </Button>
            {statusCode === 401 || statusCode === 403 ? (
                <Link className="min-h-11 text-sm text-teal-300 hover:underline" href="/sign-in">{t('propicks.loadError.signIn')}</Link>
            ) : null}
        </main>
    );
}
