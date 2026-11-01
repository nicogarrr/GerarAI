import { form13fValueToUsd } from '@/lib/form13f-value';
import { createFormatters } from '@/lib/format';
import type { Locale } from '@/lib/i18n/locale';

/** Valor 13F (dolares desde 2023, miles antes; se normaliza por fecha del informe): "$4.87B". */
export function usd(raw: number | null | undefined, reportDate: string | null | undefined, locale: Locale = 'es'): string {
    const fmt = createFormatters(locale);
    const dollars = form13fValueToUsd(raw, reportDate);
    return dollars === null ? fmt.na : fmt.formatMarketCapUsd(dollars);
}

/** Periodo del informe ("2026-06-30") en el idioma elegido: "30 jun 2026" / "30 Jun 2026". */
export function periodLabel(value: string | null | undefined, locale: Locale = 'es'): string {
    const fmt = createFormatters(locale);
    return value ? fmt.formatDate(value, { day: 'numeric', month: 'short', year: 'numeric' }, value) : fmt.na;
}
