'use client';

import { useRouter } from 'next/navigation';
import { useTransition } from 'react';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import { useLocale, useT } from '@/lib/i18n/client';
import { isLocale, LOCALE_COOKIE, type Locale } from '@/lib/i18n/locale';

/**
 * Selector de idioma (Ajustes). Escribe la cookie `gerarai_locale` y pide al
 * servidor que re-renderice con ella: cambio inmediato y persistente, sin
 * prefijos de URL. Los nombres de idioma se muestran en su propio idioma.
 */
export default function LanguageForm() {
    const t = useT();
    const locale = useLocale();
    const router = useRouter();
    const [pending, startTransition] = useTransition();

    const choose = (next: string) => {
        if (!isLocale(next) || next === locale) return;
        document.cookie = `${LOCALE_COOKIE}=${next}; path=/; max-age=31536000; samesite=lax`;
        startTransition(() => router.refresh());
    };

    return (
        <label className="flex flex-col gap-1 text-sm text-gray-300">
            {t('settings.language.label')}
            <Select disabled={pending} value={locale} onValueChange={choose}>
                <SelectTrigger className="w-64 data-[size=default]:h-11" aria-label={t('settings.language.label')}>
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    <SelectItem value={'es' satisfies Locale}>{t('settings.language.optionEs')}</SelectItem>
                    <SelectItem value={'en' satisfies Locale}>{t('settings.language.optionEn')}</SelectItem>
                </SelectContent>
            </Select>
            {pending ? <span className="text-xs text-gray-500">{t('settings.language.applying')}</span> : null}
        </label>
    );
}
